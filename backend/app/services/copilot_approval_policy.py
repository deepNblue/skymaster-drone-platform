"""Copilot 审批策略与多签服务 (v2.1 E2.5).

核心 API:
- ``get_or_default_policy``: 拉取 org 的策略，返回默认值时不落盘
- ``upsert_policy``: 更新 org 策略
- ``evaluate_requirement``: 给定 tool + risk_level，判定需要几签、要求角色
- ``add_signoff``: 添加一条签核；返回 (final_decision, need_signs, done_signs)
- ``list_signoffs``: 列举某审批的所有签核
- ``pending_approvals_for_org``: 拉取待签的 approval 列表（供 UI）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_approval import CopilotApproval
from app.models.copilot_approval_policy import (
    CopilotApprovalPolicy,
    CopilotApprovalSignoff,
)

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _risk_ge(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return _RISK_ORDER.get(a, -1) >= _RISK_ORDER.get(b, -1)


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------
async def get_policy(
    db: AsyncSession, *, org_id: UUID
) -> CopilotApprovalPolicy | None:
    res = await db.execute(
        select(CopilotApprovalPolicy).where(
            CopilotApprovalPolicy.org_id == org_id
        )
    )
    return res.scalar_one_or_none()


async def upsert_policy(
    db: AsyncSession,
    *,
    org_id: UUID,
    updated_by: UUID | None,
    dual_sign_tools: list[str] | None = None,
    dual_sign_min_risk: str | None = None,
    required_roles: list[str] | None = None,
    bypass_roles: list[str] | None = None,
) -> CopilotApprovalPolicy:
    row = await get_policy(db, org_id=org_id)
    if row is None:
        row = CopilotApprovalPolicy(
            org_id=org_id,
            dual_sign_tools=dual_sign_tools,
            dual_sign_min_risk=dual_sign_min_risk,
            required_roles=required_roles,
            bypass_roles=bypass_roles,
            updated_by=updated_by,
        )
        db.add(row)
    else:
        row.dual_sign_tools = dual_sign_tools
        row.dual_sign_min_risk = dual_sign_min_risk
        row.required_roles = required_roles
        row.bypass_roles = bypass_roles
        row.updated_by = updated_by
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Requirement evaluation
# ---------------------------------------------------------------------------
@dataclass
class ApprovalRequirement:
    needs_signs: int  # 1 or 2
    required_roles: list[str]
    reason: str


async def evaluate_requirement(
    db: AsyncSession,
    *,
    org_id: UUID,
    tool_name: str,
    risk_level: str | None,
) -> ApprovalRequirement:
    policy = await get_policy(db, org_id=org_id)
    if policy is None:
        return ApprovalRequirement(
            needs_signs=1, required_roles=[],
            reason="no policy configured; single sign",
        )
    if policy.dual_sign_tools and tool_name in policy.dual_sign_tools:
        return ApprovalRequirement(
            needs_signs=2,
            required_roles=policy.required_roles or [],
            reason=f"tool {tool_name!r} in dual_sign_tools",
        )
    if policy.dual_sign_min_risk and _risk_ge(
        risk_level, policy.dual_sign_min_risk
    ):
        return ApprovalRequirement(
            needs_signs=2,
            required_roles=policy.required_roles or [],
            reason=f"risk={risk_level} >= min_risk={policy.dual_sign_min_risk}",
        )
    return ApprovalRequirement(
        needs_signs=1, required_roles=[],
        reason="default single sign",
    )


# ---------------------------------------------------------------------------
# Signoff flow
# ---------------------------------------------------------------------------
@dataclass
class SignoffResult:
    final_decision: str | None  # "approve" / "reject" / None (still pending)
    needs_signs: int
    done_signs: int
    signoffs: list[CopilotApprovalSignoff]


async def add_signoff(
    db: AsyncSession,
    *,
    approval_id: UUID,
    org_id: UUID,
    signer_id: UUID,
    signer_role: str | None,
    decision: str,
    comment: str | None = None,
    tool_name: str,
    risk_level: str | None,
) -> SignoffResult:
    if decision not in ("approve", "reject"):
        raise ValueError(f"invalid decision: {decision}")

    # 1. Enforce policy: signer role required?
    req = await evaluate_requirement(
        db, org_id=org_id, tool_name=tool_name, risk_level=risk_level,
    )

    # 2. Prevent duplicate signer
    existing = await db.execute(
        select(CopilotApprovalSignoff).where(
            and_(
                CopilotApprovalSignoff.approval_id == approval_id,
                CopilotApprovalSignoff.signer_id == signer_id,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("signer has already signed this approval")

    # 3. Insert signoff
    sig = CopilotApprovalSignoff(
        approval_id=approval_id, org_id=org_id,
        signer_id=signer_id, signer_role=signer_role,
        decision=decision, comment=comment,
    )
    db.add(sig)
    await db.commit()
    await db.refresh(sig)

    # 4. Recompute state
    all_res = await db.execute(
        select(CopilotApprovalSignoff).where(
            CopilotApprovalSignoff.approval_id == approval_id
        ).order_by(CopilotApprovalSignoff.created_at)
    )
    signoffs = list(all_res.scalars())

    # Any reject → final reject
    if any(s.decision == "reject" for s in signoffs):
        final = "reject"
    else:
        approves = [s for s in signoffs if s.decision == "approve"]
        # Role coverage: if required_roles specified, both roles must be present
        role_ok = True
        if req.required_roles:
            present_roles = {s.signer_role for s in approves}
            for role in req.required_roles:
                if role not in present_roles:
                    role_ok = False
                    break
        if len(approves) >= req.needs_signs and role_ok:
            final = "approve"
        else:
            final = None

    # 5. If final decided, propagate to CopilotApproval row.
    if final is not None:
        approval_res = await db.execute(
            select(CopilotApproval).where(CopilotApproval.id == approval_id)
        )
        approval = approval_res.scalar_one_or_none()
        if approval is not None:
            approval.decision = final
            approval.approver_id = signer_id  # last signer
            from datetime import datetime, timezone
            approval.approved_at = datetime.now(timezone.utc)
            await db.commit()

    return SignoffResult(
        final_decision=final,
        needs_signs=req.needs_signs,
        done_signs=sum(1 for s in signoffs if s.decision == "approve"),
        signoffs=signoffs,
    )


async def list_signoffs(
    db: AsyncSession, *, approval_id: UUID, org_id: UUID
) -> list[CopilotApprovalSignoff]:
    res = await db.execute(
        select(CopilotApprovalSignoff).where(
            and_(
                CopilotApprovalSignoff.approval_id == approval_id,
                CopilotApprovalSignoff.org_id == org_id,
            )
        ).order_by(CopilotApprovalSignoff.created_at)
    )
    return list(res.scalars())


async def get_status(
    db: AsyncSession,
    *,
    approval_id: UUID,
    org_id: UUID,
    tool_name: str,
    risk_level: str | None,
) -> dict[str, Any]:
    """Non-mutating status snapshot for UI."""
    req = await evaluate_requirement(
        db, org_id=org_id, tool_name=tool_name, risk_level=risk_level,
    )
    signoffs = await list_signoffs(db, approval_id=approval_id, org_id=org_id)
    approves = [s for s in signoffs if s.decision == "approve"]
    rejects = [s for s in signoffs if s.decision == "reject"]

    final = None
    if rejects:
        final = "reject"
    else:
        role_ok = True
        if req.required_roles:
            present = {s.signer_role for s in approves}
            role_ok = all(r in present for r in req.required_roles)
        if len(approves) >= req.needs_signs and role_ok:
            final = "approve"

    return {
        "approval_id": str(approval_id),
        "needs_signs": req.needs_signs,
        "done_signs": len(approves),
        "required_roles": req.required_roles,
        "reason": req.reason,
        "final_decision": final,
        "signoffs": [
            {
                "id": str(s.id),
                "signer_id": str(s.signer_id),
                "signer_role": s.signer_role,
                "decision": s.decision,
                "comment": s.comment,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            } for s in signoffs
        ],
    }
