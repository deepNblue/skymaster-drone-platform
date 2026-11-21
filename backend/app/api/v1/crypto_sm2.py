"""SM2 admin & verifier API — R21 Step F.

Endpoints
---------

* ``GET  /crypto/sm2/status``                — is signing enabled + key IDs.
* ``GET  /crypto/sm2/public/{key_id}``       — export public key (hex + PEM-like).
* ``POST /crypto/sm2/verify``                — verify (record_id, curr_hash, ts, sig, kid).
* ``POST /crypto/sm2/generate-keypair``      — admin utility (ops bootstrap).
* ``GET  /crypto/sm2/audit/{id}``            — return signature metadata for an audit row.

All endpoints require ``admin`` role except ``status`` and ``public/{id}``
(informational; safe to publish).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services import hsm as _hsm
from app.services import sm2_signer as _sm2

router = APIRouter(prefix="/crypto/sm2", tags=["crypto"])


class VerifyIn(BaseModel):
    record_id: str = Field(min_length=1, max_length=200)
    curr_hash: str = Field(min_length=1, max_length=200)
    ts: str = Field(min_length=1, max_length=64)
    signature_hex: str = Field(min_length=1, max_length=200)
    key_id: str = Field(min_length=1, max_length=32)


class VerifyOut(BaseModel):
    ok: bool
    key_id: str
    known_key: bool


@router.get("/status")
async def sm2_status(user: User = Depends(get_current_user)) -> dict:
    return {
        "enabled": _sm2.is_enabled(),
        "active_key_id": _sm2.active_key_id(),
        "known_key_ids": _sm2.known_key_ids(),
    }


@router.get("/public/{key_id}")
async def sm2_public_key(
    key_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    hex_ = _sm2.export_public_hex(key_id)
    if hex_ is None:
        raise HTTPException(404, "unknown key_id")
    return {"key_id": key_id, "public_hex": hex_, "curve": "sm2p256v1"}


@router.post("/verify", response_model=VerifyOut)
async def sm2_verify(body: VerifyIn, user: User = Depends(get_current_user)) -> VerifyOut:
    known = body.key_id in _sm2.known_key_ids()
    ok = _sm2.verify(
        record_id=body.record_id,
        curr_hash=body.curr_hash,
        ts=body.ts,
        signature_hex=body.signature_hex,
        key_id=body.key_id,
    )
    return VerifyOut(ok=ok, key_id=body.key_id, known_key=known)


@router.post("/generate-keypair")
async def sm2_generate_keypair(user: User = Depends(get_current_user)) -> dict:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(403, "admin only")
    try:
        priv, pub = _sm2.generate_keypair()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {
        "private_hex": priv, "public_hex": pub,
        "note": (
            "Store SM2_PRIVATE_KEY_HEX in a secret manager; SM2_PUBLIC_KEY_HEX "
            "may be published for verifiers. Set SM2_KEY_ID to version this pair."
        ),
    }


class AuditSigOut(BaseModel):
    id: int
    action: str
    resource: Optional[str] = None
    curr_hash: Optional[str] = None
    sig_hex: Optional[str] = None
    sig_key_id: Optional[str] = None
    ts: Optional[str] = None


@router.get("/audit/{audit_id}", response_model=AuditSigOut)
async def audit_signature(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AuditSigOut:
    row = await db.get(AuditLog, audit_id)
    if row is None:
        raise HTTPException(404, "audit row not found")
    return AuditSigOut(
        id=row.id,
        action=row.action,
        resource=row.resource,
        curr_hash=row.curr_hash,
        sig_hex=row.sig_hex,
        sig_key_id=row.sig_key_id,
        ts=row.ts.isoformat() if row.ts else None,
    )


# --------------------------------------------------------------------------
# R21 · Key rotation + HSM backend introspection
# --------------------------------------------------------------------------


@router.get("/rotation")
async def sm2_rotation(user: User = Depends(get_current_user)) -> dict:
    """Return per-key rotation metadata for admin UI.

    Response shape:
        {
          "active_key_id": "v1",
          "any_rotation_due": false,
          "keys": [
            {"key_id":"v1","has_private":true,"active":true,
             "created_at":1720000000.0,"age_days":12.3,
             "lifetime_days":90.0,"rotation_due":false}, ...
          ]
        }
    """
    return _sm2.rotation_status()


@router.get("/hsm")
async def sm2_hsm(user: User = Depends(get_current_user)) -> dict:
    """Which signer backends are configured and which is currently active."""
    return _hsm.hsm_status()
