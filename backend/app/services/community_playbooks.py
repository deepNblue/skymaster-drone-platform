"""T11.2 · Community playbook service — CRUD, moderation, fork.

Trust boundary
==============
Any user can submit a playbook. Before it's visible to other orgs it
must be approved by a reviewer with role='admin'. Rejected submissions
stay in the DB (author's org can still see them) with rejected_reason
so the author knows why.

The forking operation ("install into my org's workflows") is what
actually connects community → org-scoped. It's a pure DB write —
no execution happens until the user runs the forked workflow through
the normal /run path.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community_playbook import CommunityPlaybook
from app.models.copilot_workflow import CopilotWorkflow
from app.services.tool_registry import build_default_registry
from app.services.workflow_dsl import parse_workflow, validate_workflow


class PlaybookError(Exception):
    """Business-logic error surface — API layer maps to 400/403/404."""


VALID_STATUSES = frozenset({"pending", "approved", "rejected"})

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise PlaybookError(
            "slug must be lowercase kebab-case (a-z, 0-9, -)"
        )
    if len(slug) > 60:
        raise PlaybookError("slug too long (max 60 chars)")
    return f"user-{slug}"


async def _assert_dsl_valid(dsl_yaml: str) -> str:
    """Reuse the same DSL validator as /validate + /run. Return the
    workflow's declared name."""
    try:
        doc = parse_workflow(dsl_yaml)
        registry = build_default_registry()
        validate_workflow(doc, registry)
    except Exception as exc:
        raise PlaybookError(f"DSL validation failed: {exc}") from exc
    return doc.name


async def submit_playbook(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    author_user_id: uuid.UUID,
    slug: str,
    name: str,
    description: str,
    dsl_yaml: str,
    sample_inputs: dict[str, Any] | None,
    tags: list[str] | None,
) -> CommunityPlaybook:
    prefixed_slug = _validate_slug(slug)
    await _assert_dsl_valid(dsl_yaml)

    # slug uniqueness — surface a clean error before hitting the DB
    # constraint.
    existing = (await db.execute(
        select(CommunityPlaybook).where(
            CommunityPlaybook.slug == prefixed_slug,
            CommunityPlaybook.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise PlaybookError(f"slug '{slug}' is already taken")

    row = CommunityPlaybook(
        org_id=org_id,
        author_user_id=author_user_id,
        slug=prefixed_slug,
        name=name.strip(),
        description=(description or "").strip(),
        dsl_yaml=dsl_yaml,
        sample_inputs_json=sample_inputs or {},
        tags=list(tags or []),
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_playbooks(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    status: str | None = None,
    include_own_pending: bool = False,
    limit: int = 50,
) -> list[CommunityPlaybook]:
    """List community playbooks.

    * Public listing: only ``status='approved'`` visible.
    * When ``include_own_pending=True`` AND ``org_id`` is provided, also
      return the caller org's pending/rejected submissions.
    """
    q = select(CommunityPlaybook).where(
        CommunityPlaybook.deleted_at.is_(None),
    )
    if status is not None:
        if status not in VALID_STATUSES:
            raise PlaybookError(f"invalid status filter: {status}")
        q = q.where(CommunityPlaybook.status == status)
    elif include_own_pending and org_id is not None:
        from sqlalchemy import or_
        q = q.where(
            or_(
                CommunityPlaybook.status == "approved",
                CommunityPlaybook.org_id == org_id,
            )
        )
    else:
        q = q.where(CommunityPlaybook.status == "approved")

    q = q.order_by(CommunityPlaybook.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def get_playbook(
    db: AsyncSession, *, slug: str,
) -> CommunityPlaybook | None:
    q = select(CommunityPlaybook).where(
        CommunityPlaybook.slug == slug,
        CommunityPlaybook.deleted_at.is_(None),
    )
    return (await db.execute(q)).scalar_one_or_none()


async def moderate_playbook(
    db: AsyncSession,
    *,
    slug: str,
    reviewer_id: uuid.UUID,
    approve: bool,
    reason: str | None = None,
) -> CommunityPlaybook:
    row = await get_playbook(db, slug=slug)
    if row is None:
        raise PlaybookError(f"playbook '{slug}' not found")

    row.status = "approved" if approve else "rejected"
    row.rejected_reason = None if approve else (reason or "").strip() or "no reason given"
    row.reviewed_by = reviewer_id
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def fork_to_workflow(
    db: AsyncSession,
    *,
    slug: str,
    target_org_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> CopilotWorkflow:
    """Install an approved community playbook into the caller's
    workflows table. Returns the newly created workflow row.

    Rejects if the playbook isn't approved (unless caller's org == author's org).
    """
    playbook = await get_playbook(db, slug=slug)
    if playbook is None:
        raise PlaybookError(f"playbook '{slug}' not found")

    if playbook.status != "approved" and playbook.org_id != target_org_id:
        raise PlaybookError(
            "cannot fork non-approved playbook from another org",
        )

    # Name uniqueness within target org — append a suffix if the
    # forker already has a workflow with that name.
    base_name = playbook.name
    candidate = base_name
    i = 1
    while True:
        exists = (await db.execute(
            select(CopilotWorkflow).where(
                CopilotWorkflow.org_id == target_org_id,
                CopilotWorkflow.name == candidate,
                CopilotWorkflow.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if exists is None:
            break
        i += 1
        candidate = f"{base_name} ({i})"

    wf = CopilotWorkflow(
        org_id=target_org_id,
        owner_user_id=target_user_id,
        name=candidate,
        description=(
            f"[Forked from community playbook '{playbook.slug}']\n"
            f"{playbook.description}"
        ),
        dsl_yaml=playbook.dsl_yaml,
        version=1,
    )
    db.add(wf)

    playbook.install_count = (playbook.install_count or 0) + 1
    await db.commit()
    await db.refresh(wf)
    return wf


async def delete_playbook(
    db: AsyncSession,
    *,
    slug: str,
    requester_org_id: uuid.UUID,
    requester_user_id: uuid.UUID,
    is_admin: bool,
) -> bool:
    row = await get_playbook(db, slug=slug)
    if row is None:
        return False
    # Only author (same org) OR admin can delete.
    if not is_admin and row.author_user_id != requester_user_id:
        raise PlaybookError("only the author or an admin can delete")
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True
