"""Three-Officer Separation of Duty API — v2.0 R19.

Endpoints
=========

- GET  /api/v1/admin/officers              list all officer assignments
- POST /api/v1/admin/officers/grant        assign officer_role (security_officer only)
- POST /api/v1/admin/officers/revoke       clear officer_role
- GET  /api/v1/admin/officers/matrix       expose the permission matrix
- POST /api/v1/admin/officers/dual-sign    demo dual-control check
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.audit_middleware import _write_audit as audit
from app.services.officer_matrix import (
    OFFICER_ROLES,
    PERMISSION_MATRIX,
    dual_control_check,
    require_action,
    require_officer,
    validate_officer_assignment,
)

router = APIRouter(prefix="/admin/officers", tags=["compliance-officers"])


# --- Schemas ---------------------------------------------------------------


class OfficerOut(BaseModel):
    id: UUID
    email: str
    role: str
    officer_role: str | None
    is_active: bool

    class Config:
        from_attributes = True


class GrantBody(BaseModel):
    user_id: UUID
    officer_role: str = Field(..., pattern="^(system_officer|security_officer|audit_officer)$")


class RevokeBody(BaseModel):
    user_id: UUID


class DualSignBody(BaseModel):
    action: str
    cosigner_id: UUID


# --- Endpoints -------------------------------------------------------------


@router.get("/matrix")
async def get_matrix(
    _: User = Depends(require_action("officer.list")),
) -> dict:
    """Return the permission matrix — used by frontend to render UI hints."""
    return {
        "officers": sorted(OFFICER_ROLES),
        "matrix": {k: sorted(v) for k, v in PERMISSION_MATRIX.items()},
    }


@router.get("", response_model=list[OfficerOut])
async def list_officers(
    _: User = Depends(require_action("officer.list")),
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    rows = (await db.execute(
        select(User).where(User.officer_role.isnot(None)).order_by(User.officer_role, User.email)
    )).scalars().all()
    return list(rows)


@router.post("/grant", response_model=OfficerOut)
async def grant_officer(
    body: GrantBody,
    request: Request,
    actor: User = Depends(require_action("officer.grant")),
    db: AsyncSession = Depends(get_db),
) -> User:
    target = await db.get(User, body.user_id)
    if target is None:
        raise HTTPException(404, "target user not found")
    if target.id == actor.id:
        raise HTTPException(403, "不能给自己授权三员身份 · 违反自我提权禁令")

    validate_officer_assignment(target, body.officer_role)
    prev = target.officer_role
    target.officer_role = body.officer_role
    await db.commit()
    await db.refresh(target)

    await audit(
        request.app.state,
        action="officer.grant",
        actor_id=actor.id,
        actor_role=actor.officer_role or actor.role,
        resource=f"user:{target.id}",
        diff={"before": prev, "after": body.officer_role, "target_email": target.email},
        ip=(request.client.host if request.client else None),
        ua=request.headers.get("user-agent"),
    )
    return target


@router.post("/revoke", response_model=OfficerOut)
async def revoke_officer(
    body: RevokeBody,
    request: Request,
    actor: User = Depends(require_action("officer.revoke")),
    db: AsyncSession = Depends(get_db),
) -> User:
    target = await db.get(User, body.user_id)
    if target is None:
        raise HTTPException(404, "target user not found")
    if target.id == actor.id:
        raise HTTPException(403, "不能撤销自己的身份 · 会造成安全员真空")

    prev = target.officer_role
    target.officer_role = None
    await db.commit()
    await db.refresh(target)

    await audit(
        request.app.state,
        action="officer.revoke",
        actor_id=actor.id,
        actor_role=actor.officer_role or actor.role,
        resource=f"user:{target.id}",
        diff={"before": prev, "after": None, "target_email": target.email},
        ip=(request.client.host if request.client else None),
        ua=request.headers.get("user-agent"),
    )
    return target


@router.post("/dual-sign")
async def dual_sign_demo(
    body: DualSignBody,
    request: Request,
    actor: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify two officers together can perform ``action``.

    Useful for high-risk ops (backup.restore, key.destroy). Just validates
    — actual mutation happens in the caller.
    """
    cosigner = await db.get(User, body.cosigner_id)
    dual_control_check(actor, cosigner, body.action)
    await audit(
        request.app.state,
        action="dual_sign.verify",
        actor_id=actor.id,
        actor_role=actor.officer_role or actor.role,
        resource=body.action,
        diff={
            "actor_officer": actor.officer_role,
            "cosigner_id": str(body.cosigner_id),
            "cosigner_officer": cosigner.officer_role if cosigner else None,
        },
        ip=(request.client.host if request.client else None),
        ua=request.headers.get("user-agent"),
    )
    return {
        "ok": True,
        "action": body.action,
        "actor": {"id": str(actor.id), "officer": actor.officer_role},
        "cosigner": {"id": str(cosigner.id), "officer": cosigner.officer_role},
    }
