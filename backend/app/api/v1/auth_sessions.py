"""Session management + password change endpoints (R16)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.active_session import ActiveSession
from app.models.revoked_token import RevokedToken
from app.models.user import User
from app.services.auth import hash_password, verify_password
from app.services.password_policy import validate_password, PasswordPolicyError

router = APIRouter(prefix="/auth", tags=["auth-sessions"])


# --- helpers ---------------------------------------------------------------


def _parse_device_label(ua: Optional[str]) -> Optional[str]:
    """Best-effort UA parsing — avoids extra dependencies."""
    if not ua:
        return None
    ua_lower = ua.lower()
    if "iphone" in ua_lower:
        return "iPhone"
    if "ipad" in ua_lower:
        return "iPad"
    if "android" in ua_lower:
        return "Android"
    if "windows" in ua_lower:
        if "chrome" in ua_lower:
            return "Windows · Chrome"
        if "edge" in ua_lower or "edg/" in ua_lower:
            return "Windows · Edge"
        if "firefox" in ua_lower:
            return "Windows · Firefox"
        return "Windows"
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        if "safari" in ua_lower and "chrome" not in ua_lower:
            return "macOS · Safari"
        if "chrome" in ua_lower:
            return "macOS · Chrome"
        return "macOS"
    if "linux" in ua_lower:
        return "Linux"
    return "Unknown"


# --- Schemas ---------------------------------------------------------------


class SessionOut(BaseModel):
    id: UUID
    jti: str
    ip: Optional[str]
    country: Optional[str]
    user_agent: Optional[str]
    device_label: Optional[str]
    created_at: datetime
    last_seen_at: datetime
    is_current: bool = False

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


# --- Endpoints -------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionOut]:
    """List all active (non-revoked) sessions for the current user."""
    rows = (await db.execute(
        select(ActiveSession)
        .where(
            ActiveSession.user_id == user.id,
            ActiveSession.revoked_at.is_(None),
        )
        .order_by(ActiveSession.last_seen_at.desc())
    )).scalars().all()

    # Mark the "current" session by matching the access token's jti/subject.
    current_jti = _current_jti_from_request(request)
    out: list[SessionOut] = []
    for r in rows:
        obj = SessionOut.model_validate(r)
        obj.is_current = current_jti is not None and r.jti == current_jti
        out.append(obj)
    return out


def _current_jti_from_request(request: Request) -> Optional[str]:
    """Best-effort — decode access token to find its jti/session marker."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        from app.services.auth import decode_token
        payload = decode_token(auth[7:])
        # Access tokens carry their own jti; sessions are keyed on the
        # refresh-token jti. If the access token stores its parent
        # refresh jti under `rjti` we use that; otherwise fall back to
        # the access `jti` (still useful for "which session did this
        # request come from" heuristics).
        return payload.get("rjti") or payload.get("jti")
    except Exception:  # noqa: BLE001
        return None


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke a specific active session by ID."""
    row = (await db.execute(
        select(ActiveSession).where(
            ActiveSession.id == session_id,
            ActiveSession.user_id == user.id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Session not found")
    if row.revoked_at is not None:
        return {"ok": True, "already_revoked": True}
    now = datetime.now(tz=timezone.utc)
    row.revoked_at = now
    db.add(RevokedToken(jti=row.jti, exp=now, revoked_at=now, reason="user_session_revoke"))
    await db.commit()
    return {"ok": True, "id": str(session_id)}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Logout everywhere except the current session."""
    current = _current_jti_from_request(request)
    rows = (await db.execute(
        select(ActiveSession).where(
            ActiveSession.user_id == user.id,
            ActiveSession.revoked_at.is_(None),
        )
    )).scalars().all()
    now = datetime.now(tz=timezone.utc)
    count = 0
    for r in rows:
        if current and r.jti == current:
            continue
        r.revoked_at = now
        db.add(RevokedToken(jti=r.jti, exp=now, revoked_at=now, reason="user_revoke_others"))
        count += 1
    await db.commit()
    return {"ok": True, "revoked_count": count}


@router.post("/change-password")
async def change_password_r16(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Alias for /auth/password — R16 version that returns revoked_sessions.

    Kept as a distinct endpoint because clients built against R15 send
    ``{current_password, new_password}`` field names while /auth/password
    accepts ``{old_password, new_password}``.
    """
    if not verify_password(body.current_password, user.hashed_pw):
        raise HTTPException(401, "Current password is incorrect")

    try:
        validate_password(body.new_password)
    except PasswordPolicyError as e:
        raise HTTPException(400, str(e))

    if verify_password(body.new_password, user.hashed_pw):
        raise HTTPException(400, "New password must differ from current password")

    user.hashed_pw = hash_password(body.new_password)

    # Revoke sibling sessions.
    current_jti = _current_jti_from_request(request)
    rows = (await db.execute(
        select(ActiveSession).where(
            ActiveSession.user_id == user.id,
            ActiveSession.revoked_at.is_(None),
        )
    )).scalars().all()
    now = datetime.now(tz=timezone.utc)
    revoked = 0
    for r in rows:
        if current_jti and r.jti == current_jti:
            continue
        r.revoked_at = now
        db.add(RevokedToken(jti=r.jti, exp=now, revoked_at=now, reason="password_change"))
        revoked += 1

    await db.commit()
    return {
        "ok": True,
        "revoked_sessions": revoked,
        "message": f"密码已修改，其他 {revoked} 个设备已强制登出",
    }
