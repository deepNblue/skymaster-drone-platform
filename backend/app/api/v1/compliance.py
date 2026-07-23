"""Admin API for the compliance / 国密 gateway.

Exposes:
  - GET  /api/v1/admin/compliance/status
  - POST /api/v1/admin/compliance/toggle   {enabled, mode, modules}
  - POST /api/v1/admin/compliance/verify-audit-chain

Only ``admin`` role users can toggle. All operations themselves are audited.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.crypto_gateway import gm
from app.services.audit_middleware import _write_audit as audit
from app.services.officer_matrix import require_action

router = APIRouter(prefix="/admin/compliance", tags=["compliance"])


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(403, "admin role required")


class ToggleBody(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = Field(default=None, pattern="^(off|hash|full)$")
    modules: Optional[list[str]] = None


@router.get("/status")
async def compliance_status(user: User = Depends(get_current_user)) -> dict:
    _require_admin(user)
    return gm.status()


@router.post("/toggle")
async def compliance_toggle(
    body: ToggleBody,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    prev = gm.status()
    new = gm.apply(
        enabled=body.enabled,
        mode=body.mode,
        modules=body.modules,
    )
    # This admin op MUST be auditable.
    await audit(
        request.app.state,
        action="compliance.toggle",
        actor_id=user.id,
        actor_role=user.role,
        resource="gm",
        diff={"before": prev, "after": new},
        ip=(request.client.host if request.client else None),
        ua=request.headers.get("user-agent"),
    )
    return {"ok": True, "before": prev, "after": new}


@router.post("/verify-audit-chain")
async def verify_chain(
    limit: int = 500,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Walk the audit_log hash chain and report any broken link.

    Cheap safety check for auditors — returns the first inconsistency (or
    OK). Skips rows where curr_hash is NULL (i.e. written when 国密 was off).
    """
    _require_admin(user)
    import json
    from app.services.sm_crypto import sm3_chain

    rows = (await db.execute(
        select(AuditLog)
        .where(AuditLog.curr_hash.isnot(None))
        .order_by(AuditLog.id.asc())
        .limit(limit)
    )).scalars().all()

    prev_hex = "0" * 64
    broken = None
    for r in rows:
        payload = json.dumps(
            {"a": r.action, "r": r.resource, "d": r.diff, "act": str(r.actor_id)},
            sort_keys=True, ensure_ascii=False,
        )
        expect = sm3_chain(bytes.fromhex(r.prev_hash or prev_hex), payload).hex()
        if r.prev_hash != prev_hex or r.curr_hash != expect:
            broken = {
                "id": r.id,
                "expected_prev": prev_hex,
                "stored_prev": r.prev_hash,
                "expected_curr": expect,
                "stored_curr": r.curr_hash,
            }
            break
        prev_hex = r.curr_hash
    return {
        "checked": len(rows),
        "ok": broken is None,
        "broken_at": broken,
    }
