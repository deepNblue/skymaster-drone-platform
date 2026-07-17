"""API: /copilot/approval-policy — E2.5 双签/多签审批策略."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import copilot_approval_policy as svc

router = APIRouter(prefix="/copilot/approval-policy", tags=["copilot-approval-policy"])

_VALID_RISK = {"low", "medium", "high", "critical"}


class PolicyIn(BaseModel):
    dual_sign_tools: list[str] | None = None
    dual_sign_min_risk: str | None = Field(default=None)
    required_roles: list[str] | None = None
    bypass_roles: list[str] | None = None


class PolicyOut(BaseModel):
    org_id: UUID
    dual_sign_tools: list[str] | None = None
    dual_sign_min_risk: str | None = None
    required_roles: list[str] | None = None
    bypass_roles: list[str] | None = None


class SignoffIn(BaseModel):
    decision: str = Field(..., description="approve|reject")
    comment: str | None = None
    tool_name: str = Field(..., description="Tool being approved (from CopilotApproval.required_reason)")
    risk_level: str | None = None


@router.get("/me", response_model=PolicyOut | None)
async def api_get_policy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut | None:
    row = await svc.get_policy(db, org_id=user.org_id)
    if row is None:
        return None
    return PolicyOut(
        org_id=row.org_id,
        dual_sign_tools=row.dual_sign_tools,
        dual_sign_min_risk=row.dual_sign_min_risk,
        required_roles=row.required_roles,
        bypass_roles=row.bypass_roles,
    )


@router.put("/me", response_model=PolicyOut)
async def api_upsert_policy(
    body: PolicyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut:
    if body.dual_sign_min_risk and body.dual_sign_min_risk not in _VALID_RISK:
        raise HTTPException(400, f"invalid dual_sign_min_risk: {body.dual_sign_min_risk}")
    row = await svc.upsert_policy(
        db,
        org_id=user.org_id, updated_by=user.id,
        dual_sign_tools=body.dual_sign_tools,
        dual_sign_min_risk=body.dual_sign_min_risk,
        required_roles=body.required_roles,
        bypass_roles=body.bypass_roles,
    )
    return PolicyOut(
        org_id=row.org_id,
        dual_sign_tools=row.dual_sign_tools,
        dual_sign_min_risk=row.dual_sign_min_risk,
        required_roles=row.required_roles,
        bypass_roles=row.bypass_roles,
    )


@router.post("/approvals/{approval_id}/sign", response_model=dict[str, Any])
async def api_sign(
    approval_id: UUID,
    body: SignoffIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, f"invalid decision: {body.decision}")
    try:
        r = await svc.add_signoff(
            db,
            approval_id=approval_id, org_id=user.org_id,
            signer_id=user.id, signer_role=user.role,
            decision=body.decision, comment=body.comment,
            tool_name=body.tool_name, risk_level=body.risk_level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "final_decision": r.final_decision,
        "needs_signs": r.needs_signs,
        "done_signs": r.done_signs,
    }


@router.get("/approvals/{approval_id}/status", response_model=dict[str, Any])
async def api_status(
    approval_id: UUID,
    tool_name: str,
    risk_level: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await svc.get_status(
        db,
        approval_id=approval_id, org_id=user.org_id,
        tool_name=tool_name, risk_level=risk_level,
    )
