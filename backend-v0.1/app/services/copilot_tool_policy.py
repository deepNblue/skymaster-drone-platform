"""Copilot Tool Policy (v2.1 F4.4).

Encapsulates:
1. Per-org tool policy CRUD (allowlist / blocklist / risk cap).
2. Pre-flight ``evaluate`` returning one of: ``allowed``, ``blocked``,
   ``approval_required``.
3. Post-flight ``record_audit`` writing the outcome to
   ``copilot_tool_audits``.

The Copilot agent should call ``evaluate`` before every tool invocation and
call ``record_audit`` unconditionally afterwards (success, error, or blocked).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, func, insert as sa_insert, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_tool_audit import CopilotOrgToolPolicy, CopilotToolAudit
from app.services.tool_registry import ToolSpec, get_registry

# ---------------------------------------------------------------------------
# Risk tiers
# ---------------------------------------------------------------------------
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _risk_rank(level: str | None) -> int:
    if not level:
        return 0
    return _RISK_ORDER.get(level.lower(), 0)


# ---------------------------------------------------------------------------
# Evaluate result
# ---------------------------------------------------------------------------
@dataclass
class PolicyDecision:
    action: str  # allowed | blocked | approval_required
    reason: str | None = None
    risk_level: str = "low"
    permission: str = "readonly"


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------
async def get_policy(
    db: AsyncSession, *, org_id: UUID
) -> CopilotOrgToolPolicy | None:
    res = await db.execute(
        select(CopilotOrgToolPolicy).where(CopilotOrgToolPolicy.org_id == org_id)
    )
    return res.scalar_one_or_none()


async def upsert_policy(
    db: AsyncSession,
    *,
    org_id: UUID,
    allowlist: list[str] | None,
    blocklist: list[str] | None,
    max_risk_level: str | None,
    require_approval_above: str | None,
) -> CopilotOrgToolPolicy:
    """Portable upsert (avoids Postgres-only ON CONFLICT)."""

    upd = (
        sa_update(CopilotOrgToolPolicy)
        .where(CopilotOrgToolPolicy.org_id == org_id)
        .values(
            allowlist=allowlist,
            blocklist=blocklist,
            max_risk_level=max_risk_level,
            require_approval_above=require_approval_above,
        )
    )
    res = await db.execute(upd)
    if res.rowcount == 0:
        try:
            await db.execute(
                sa_insert(CopilotOrgToolPolicy).values(
                    org_id=org_id,
                    allowlist=allowlist,
                    blocklist=blocklist,
                    max_risk_level=max_risk_level,
                    require_approval_above=require_approval_above,
                )
            )
        except Exception:
            await db.execute(upd)
    await db.commit()
    got = await get_policy(db, org_id=org_id)
    assert got is not None
    return got


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------
async def evaluate(
    db: AsyncSession, *, org_id: UUID, tool_name: str
) -> PolicyDecision:
    reg = get_registry()
    spec: ToolSpec | None = reg.get(tool_name)
    if spec is None:
        return PolicyDecision(
            action="blocked",
            reason=f"unknown tool: {tool_name}",
            risk_level="low",
            permission="readonly",
        )

    policy = await get_policy(db, org_id=org_id)

    blocklist = list(policy.blocklist or []) if policy else []
    allowlist = list(policy.allowlist or []) if policy else []
    max_risk = policy.max_risk_level if policy else None
    approval_above = policy.require_approval_above if policy else None

    if tool_name in blocklist:
        return PolicyDecision(
            action="blocked",
            reason="tool is on org blocklist",
            risk_level=spec.risk_level,
            permission=spec.permission,
        )

    if allowlist and tool_name not in allowlist:
        return PolicyDecision(
            action="blocked",
            reason="tool not on org allowlist",
            risk_level=spec.risk_level,
            permission=spec.permission,
        )

    if max_risk and _risk_rank(spec.risk_level) > _risk_rank(max_risk):
        return PolicyDecision(
            action="blocked",
            reason=f"tool risk {spec.risk_level} exceeds org max {max_risk}",
            risk_level=spec.risk_level,
            permission=spec.permission,
        )

    # Sensitive tools always require approval.
    if spec.permission == "sensitive":
        return PolicyDecision(
            action="approval_required",
            reason="sensitive tool requires approval",
            risk_level=spec.risk_level,
            permission=spec.permission,
        )

    # Risk-based approval gate (independent of permission tag).
    if approval_above and _risk_rank(spec.risk_level) >= _risk_rank(approval_above):
        return PolicyDecision(
            action="approval_required",
            reason=(
                f"tool risk {spec.risk_level} at/above org approval gate "
                f"{approval_above}"
            ),
            risk_level=spec.risk_level,
            permission=spec.permission,
        )

    return PolicyDecision(
        action="allowed",
        reason=None,
        risk_level=spec.risk_level,
        permission=spec.permission,
    )


# ---------------------------------------------------------------------------
# Audit write
# ---------------------------------------------------------------------------
def _preview(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


async def record_audit(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    tool_name: str,
    status: str,
    permission: str = "readonly",
    risk_level: str = "low",
    arguments: dict[str, Any] | None = None,
    result: Any | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
    reason: str | None = None,
    session_id: UUID | None = None,
    trace_id: UUID | None = None,
) -> CopilotToolAudit:
    row = CopilotToolAudit(
        org_id=org_id,
        user_id=user_id,
        session_id=session_id,
        trace_id=trace_id,
        tool_name=tool_name,
        permission=permission,
        risk_level=risk_level,
        status=status,
        arguments=arguments,
        result_preview=_preview(result),
        error=error,
        latency_ms=latency_ms,
        reason=reason,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Audit list + stats (for admin UI)
# ---------------------------------------------------------------------------
async def list_audits(
    db: AsyncSession,
    *,
    org_id: UUID,
    tool_name: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CopilotToolAudit]:
    stmt = select(CopilotToolAudit).where(CopilotToolAudit.org_id == org_id)
    if tool_name:
        stmt = stmt.where(CopilotToolAudit.tool_name == tool_name)
    if status:
        stmt = stmt.where(CopilotToolAudit.status == status)
    if risk_level:
        stmt = stmt.where(CopilotToolAudit.risk_level == risk_level)
    stmt = stmt.order_by(desc(CopilotToolAudit.created_at)).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def audit_stats(
    db: AsyncSession, *, org_id: UUID
) -> dict[str, dict[str, int]]:
    """Return {status: {tool_name: count}} for the org."""
    stmt = (
        select(
            CopilotToolAudit.status,
            CopilotToolAudit.tool_name,
            func.count(CopilotToolAudit.id).label("n"),
        )
        .where(CopilotToolAudit.org_id == org_id)
        .group_by(CopilotToolAudit.status, CopilotToolAudit.tool_name)
    )
    res = await db.execute(stmt)
    out: dict[str, dict[str, int]] = {}
    for status, tool, n in res.all():
        out.setdefault(status, {})[tool] = int(n)
    return out
