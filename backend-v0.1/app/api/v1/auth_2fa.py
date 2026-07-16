"""2FA setup / verify endpoints and login-with-TOTP flow."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.totp import (
    generate_secret, provisioning_uri, verify_totp, generate_backup_codes,
)

router = APIRouter(prefix="/auth/2fa", tags=["auth-2fa"])


class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    backup_codes: list[str]


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TOTPStatusResponse(BaseModel):
    enabled: bool


@router.get("/status", response_model=TOTPStatusResponse)
async def totp_status(user: User = Depends(get_current_user)) -> TOTPStatusResponse:
    return TOTPStatusResponse(enabled=bool(getattr(user, "totp_enabled", False)))


@router.post("/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TOTPSetupResponse:
    """Generate a fresh TOTP secret + backup codes.

    Backup codes are hashed with bcrypt and persisted; only their plaintext
    is returned once here — user must save immediately.
    """
    from app.models.backup_code import BackupCode
    from app.services.auth import hash_password
    from sqlalchemy import delete as sa_delete

    if getattr(user, "totp_enabled", False):
        raise HTTPException(400, "2FA is already enabled. Disable it first to re-setup.")
    secret = generate_secret()
    user.totp_secret = secret
    # Clear any pending backup codes from a prior setup attempt.
    await db.execute(
        sa_delete(BackupCode).where(BackupCode.user_id == user.id)
    )
    codes = generate_backup_codes()
    for c in codes:
        db.add(BackupCode(user_id=user.id, code_hash=hash_password(c)))
    await db.commit()
    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, user.email),
        backup_codes=codes,
    )


@router.post("/verify")
async def totp_verify(
    body: TOTPVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Confirm a fresh 2FA setup by verifying a live code from the app."""
    if not getattr(user, "totp_secret", None):
        raise HTTPException(400, "No 2FA setup pending; call /2fa/setup first")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(400, "Invalid TOTP code")
    user.totp_enabled = True
    await db.commit()
    return {"ok": True, "enabled": True}


@router.post("/disable")
async def totp_disable(
    body: TOTPVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Disable 2FA — requires proving a valid TOTP one more time.

    Also clears any remaining backup codes.
    """
    from app.models.backup_code import BackupCode
    from sqlalchemy import delete as sa_delete

    if not getattr(user, "totp_enabled", False):
        raise HTTPException(400, "2FA not enabled")
    if not verify_totp(user.totp_secret or "", body.code):
        raise HTTPException(400, "Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))
    await db.commit()
    return {"ok": True, "enabled": False}


@router.post("/backup-codes/regenerate", response_model=TOTPSetupResponse)
async def regenerate_backup_codes(
    body: TOTPVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TOTPSetupResponse:
    """Wipe existing backup codes and issue a fresh 10 — requires TOTP proof."""
    from app.models.backup_code import BackupCode
    from app.services.auth import hash_password
    from sqlalchemy import delete as sa_delete

    if not getattr(user, "totp_enabled", False):
        raise HTTPException(400, "2FA not enabled")
    if not verify_totp(user.totp_secret or "", body.code):
        raise HTTPException(400, "Invalid TOTP code")

    await db.execute(sa_delete(BackupCode).where(BackupCode.user_id == user.id))
    codes = generate_backup_codes()
    for c in codes:
        db.add(BackupCode(user_id=user.id, code_hash=hash_password(c)))
    await db.commit()
    return TOTPSetupResponse(
        secret=user.totp_secret or "",
        provisioning_uri="",
        backup_codes=codes,
    )
