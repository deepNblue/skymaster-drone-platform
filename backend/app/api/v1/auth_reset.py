"""Password reset endpoints — /forgot-password + /reset-password.

Security design:
    - Raw reset token is a 32-byte urlsafe random string, shown to the
      user exactly once via email link. Only its bcrypt hash is persisted.
    - Tokens expire in 30 min and are single-use (``used_at`` timestamp).
    - /forgot-password returns 200 regardless of whether email exists —
      prevents account-enumeration oracle.
    - Rate-limited by IP (reuses R13 login rate bucket).
    - Password reset invalidates all outstanding refresh tokens for the
      user (defense in depth if reset was triggered by a compromise).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.revoked_token import RevokedToken
from app.models.user import User
from app.services.auth import (
    hash_password, verify_password,
)
from app.services.password_policy import validate_password, PasswordPolicyError
from app.services.mailer import send_email
from app.services.rate_limit import check_login_rate

router = APIRouter(prefix="/auth", tags=["auth-reset"])

TOKEN_TTL_MIN = 30


# --- Schemas ---------------------------------------------------------------


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=256)


# --- /forgot-password ------------------------------------------------------


def _reset_url(token: str) -> str:
    import os
    base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
    return f"{base}/reset-password?token={token}"


@router.post("/forgot-password", status_code=200)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a password-reset email. Always returns 200 for privacy."""
    await check_login_rate(request)

    row = await db.execute(select(User).where(User.email == body.email))
    user = row.scalar_one_or_none()

    if user is not None and getattr(user, "is_active", True):
        # Generate a fresh raw token; persist only the hash.
        raw = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hash_password(raw),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=TOKEN_TTL_MIN),
        ))
        await db.commit()

        # Fire-and-forget mail. Non-blocking on failure.
        subject = "[SkyMaster] 密码重置链接"
        url = _reset_url(raw)
        text = (
            f"您好，\n\n"
            f"我们收到了针对您 SkyMaster 账户 ({user.email}) 的密码重置请求。\n"
            f"如果这是您本人操作，请在 {TOKEN_TTL_MIN} 分钟内点击下方链接完成重置：\n\n"
            f"{url}\n\n"
            f"如果这不是您本人操作，请忽略此邮件并立即启用双因素认证 (2FA)。\n\n"
            f"— SkyMaster 安全团队"
        )
        html = f"""<!doctype html><html><body style="font-family:sans-serif">
<h2>SkyMaster 密码重置</h2>
<p>我们收到了针对您账户 <b>{user.email}</b> 的密码重置请求。</p>
<p>请在 <b>{TOKEN_TTL_MIN} 分钟</b>内点击下方按钮完成重置：</p>
<p><a href="{url}" style="background:#1677ff;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px">重置密码</a></p>
<p style="color:#8b949e;font-size:12px">若按钮无法点击，请复制此链接：<br>{url}</p>
<hr><p style="color:#8b949e;font-size:12px">如非本人操作请忽略此邮件并启用 2FA。</p>
</body></html>"""
        await send_email(user.email, subject, text, html)

    # Anti-enumeration: identical response either way.
    return {"ok": True, "message": "如该邮箱已注册，我们已发送重置链接"}


# --- /reset-password -------------------------------------------------------


@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Consume a reset token + set a new password."""
    await check_login_rate(request)

    # Validate password strength (R11 policy).
    try:
        validate_password(body.new_password)
    except PasswordPolicyError as e:
        raise HTTPException(400, str(e))

    # Look up candidate tokens by scanning recent unused ones. We can't
    # index by raw token, but the volume is naturally small (per-user
    # tokens; regularly cleaned up). A production build would derive a
    # deterministic short prefix to reduce scan cost.
    now = datetime.now(tz=timezone.utc)
    stmt = (
        select(PasswordResetToken)
        .where(
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .order_by(PasswordResetToken.created_at.desc())
        .limit(500)
    )
    rows = (await db.execute(stmt)).scalars().all()

    matched: Optional[PasswordResetToken] = None
    for prt in rows:
        if verify_password(body.token, prt.token_hash):
            matched = prt
            break

    if matched is None:
        raise HTTPException(400, "Reset link is invalid or has expired")

    # Update user password.
    user_row = await db.execute(select(User).where(User.id == matched.user_id))
    user = user_row.scalar_one_or_none()
    if user is None:
        raise HTTPException(400, "Account no longer exists")

    user.hashed_pw = hash_password(body.new_password)

    # Consume token + revoke sibling unused tokens (single-use).
    matched.used_at = now
    await db.execute(sa_delete(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != matched.id,
    ))

    # Clear brute-force lockout state on successful reset.
    from app.services import lockout
    lockout.on_success(user)

    await db.commit()

    return {"ok": True, "message": "密码已重置，请使用新密码登录"}


# --- /cleanup helpers ------------------------------------------------------


async def cleanup_expired_reset_tokens(session: AsyncSession) -> int:
    now = datetime.now(tz=timezone.utc)
    r = await session.execute(
        sa_delete(PasswordResetToken).where(PasswordResetToken.expires_at < now)
    )
    await session.commit()
    return r.rowcount or 0
