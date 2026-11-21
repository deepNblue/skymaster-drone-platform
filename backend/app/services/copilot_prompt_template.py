"""F4.2 · Copilot prompt template service.

Version chain per persona with a single active version, safe activate
(atomically demotes prior active), rollback to prior versions, and
diff/lookup helpers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from difflib import unified_diff
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_prompt_template import (
    VALID_PERSONAS, CopilotPromptTemplate,
)


class PromptTemplateError(Exception):
    pass


# ------------------------- Create -------------------------

async def create_version(
    db: AsyncSession, *,
    persona: str,
    name: str,
    system_prompt: str,
    notes: str | None = None,
    activate: bool = False,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Create the next version for a persona (auto-increment)."""
    if persona not in VALID_PERSONAS:
        raise PromptTemplateError(
            f"invalid persona: {persona}",
        )
    if not name or len(name) > 128:
        raise PromptTemplateError(
            "name must be 1..128 chars",
        )
    if not system_prompt or len(system_prompt) > 16000:
        raise PromptTemplateError(
            "system_prompt must be 1..16000 chars",
        )

    # Next version number for this persona.
    next_ver = int((await db.execute(
        select(func.coalesce(
            func.max(CopilotPromptTemplate.version), 0,
        )).where(CopilotPromptTemplate.persona == persona),
    )).scalar() or 0) + 1

    tpl = CopilotPromptTemplate(
        persona=persona,
        version=next_ver,
        name=name,
        system_prompt=system_prompt,
        notes=notes,
        is_active=False,
        created_by=created_by,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)

    if activate:
        await activate_version(
            db, persona=persona, version=next_ver,
        )
        await db.refresh(tpl)

    return _serialize(tpl)


# ------------------------- Activate / rollback -------------------------

async def activate_version(
    db: AsyncSession, *, persona: str, version: int,
) -> dict[str, Any]:
    """Atomically activate one version, demote all others.

    Two UPDATE statements in the same transaction — safe under our
    single-writer model (no need for advisory lock at this scale).
    """
    if persona not in VALID_PERSONAS:
        raise PromptTemplateError(f"invalid persona: {persona}")

    q = select(CopilotPromptTemplate).where(
        CopilotPromptTemplate.persona == persona,
        CopilotPromptTemplate.version == version,
    )
    target = (await db.execute(q)).scalar_one_or_none()
    if target is None:
        raise PromptTemplateError("version not found")

    # Demote existing active(s) for this persona.
    await db.execute(
        update(CopilotPromptTemplate).where(
            CopilotPromptTemplate.persona == persona,
            CopilotPromptTemplate.is_active.is_(True),
        ).values(is_active=False),
    )
    # Promote target.
    target.is_active = True
    await db.commit()
    await db.refresh(target)
    return _serialize(target)


async def rollback_to_previous(
    db: AsyncSession, *, persona: str,
) -> dict[str, Any] | None:
    """Activate the newest non-active version older than current active.

    Returns None if no candidate.
    """
    if persona not in VALID_PERSONAS:
        raise PromptTemplateError(f"invalid persona: {persona}")

    # Current active.
    active = (await db.execute(
        select(CopilotPromptTemplate).where(
            CopilotPromptTemplate.persona == persona,
            CopilotPromptTemplate.is_active.is_(True),
        ),
    )).scalar_one_or_none()
    active_ver = active.version if active else None

    q = select(CopilotPromptTemplate).where(
        CopilotPromptTemplate.persona == persona,
    )
    if active_ver is not None:
        q = q.where(CopilotPromptTemplate.version < active_ver)
    q = q.order_by(CopilotPromptTemplate.version.desc()).limit(1)

    prev = (await db.execute(q)).scalar_one_or_none()
    if prev is None:
        return None
    return await activate_version(
        db, persona=persona, version=prev.version,
    )


# ------------------------- Read -------------------------

async def list_versions(
    db: AsyncSession, *, persona: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict[str, Any]]:
    q = select(CopilotPromptTemplate).order_by(
        CopilotPromptTemplate.persona,
        CopilotPromptTemplate.version.desc(),
    ).limit(min(limit, 500)).offset(offset)
    if persona is not None:
        if persona not in VALID_PERSONAS:
            raise PromptTemplateError(f"invalid persona: {persona}")
        q = q.where(CopilotPromptTemplate.persona == persona)
    rows = (await db.execute(q)).scalars().all()
    return [_serialize(t) for t in rows]


async def get_active(
    db: AsyncSession, *, persona: str,
) -> dict[str, Any] | None:
    if persona not in VALID_PERSONAS:
        raise PromptTemplateError(f"invalid persona: {persona}")
    q = select(CopilotPromptTemplate).where(
        CopilotPromptTemplate.persona == persona,
        CopilotPromptTemplate.is_active.is_(True),
    )
    t = (await db.execute(q)).scalar_one_or_none()
    return _serialize(t) if t else None


async def get_active_prompt_text(
    db: AsyncSession, *, persona: str,
) -> str | None:
    """Runtime hook for CopilotSessionV2 to fetch its system prompt."""
    row = await get_active(db, persona=persona)
    return row["system_prompt"] if row else None


async def get_version(
    db: AsyncSession, *, persona: str, version: int,
) -> dict[str, Any] | None:
    q = select(CopilotPromptTemplate).where(
        CopilotPromptTemplate.persona == persona,
        CopilotPromptTemplate.version == version,
    )
    t = (await db.execute(q)).scalar_one_or_none()
    return _serialize(t) if t else None


# ------------------------- Diff -------------------------

async def diff_versions(
    db: AsyncSession, *,
    persona: str, from_version: int, to_version: int,
) -> dict[str, Any]:
    """Unified diff of system_prompt between two versions."""
    a = await get_version(db, persona=persona, version=from_version)
    b = await get_version(db, persona=persona, version=to_version)
    if a is None or b is None:
        raise PromptTemplateError("one or both versions not found")
    a_lines = a["system_prompt"].splitlines(keepends=True)
    b_lines = b["system_prompt"].splitlines(keepends=True)
    diff = "".join(unified_diff(
        a_lines, b_lines,
        fromfile=f"v{from_version}", tofile=f"v{to_version}",
        n=3,
    ))
    return {
        "persona": persona,
        "from_version": from_version,
        "to_version": to_version,
        "diff": diff,
        "changed": diff != "",
    }


# ------------------------- helpers -------------------------

def _serialize(t: CopilotPromptTemplate) -> dict[str, Any]:
    ca = t.created_at
    if ca is not None and ca.tzinfo is None:
        ca = ca.replace(tzinfo=timezone.utc)
    return {
        "id": str(t.id),
        "persona": t.persona,
        "version": t.version,
        "name": t.name,
        "system_prompt": t.system_prompt,
        "notes": t.notes,
        "is_active": bool(t.is_active),
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": ca.isoformat() if ca else None,
    }
