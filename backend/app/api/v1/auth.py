"""Authentication endpoints — /auth/login, /auth/refresh, /auth/logout, /auth/me, /auth/password."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.revoked_token import RevokedToken
from app.models.user import User
from app.schemas.auth import (
    LoginRequest, TokenResponse, UserOut,
    RefreshRequest, PasswordChangeRequest,
)
from app.services.auth import (
    create_access_token, create_refresh_token, decode_token,
    hash_password, verify_password,
)
from app.services.password_policy import validate_password, PasswordPolicyError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    from app.services import lockout
    from app.services.rate_limit import check_login_rate
    from app.services.login_recorder import record_login, client_ip_from_request
    from app.services.anomaly_detector import check_anomaly, notify_admin

    # IP-based rate limit runs FIRST — before any DB or bcrypt work.
    try:
        await check_login_rate(request)
    except HTTPException:
        await record_login(
            db, user_id=None, email=payload.email, method="password",
            outcome="rate_limit",
            ip=client_ip_from_request(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
        raise

    ip = client_ip_from_request(request)
    ua = request.headers.get("user-agent")

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    # Constant-time-ish: always run bcrypt even when user is None to
    # avoid trivial user-existence oracle via timing.
    if user is None:
        # Waste some CPU to keep timing roughly similar.
        verify_password(payload.password, "$2b$12$" + "x" * 53)
        await record_login(
            db, user_id=None, email=payload.email, method="password",
            outcome="invalid_email", ip=ip, user_agent=ua,
        )
        await db.commit()
        raise HTTPException(401, "Invalid email or password")

    # Lockout check runs before password verify.
    if lockout.is_locked(user):
        await record_login(
            db, user_id=user.id, email=user.email, method="password",
            outcome="locked", ip=ip, user_agent=ua,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Account locked due to too many failed attempts. "
                f"Try again after {user.locked_until.isoformat()}"
            ),
        )
    if hasattr(user, "is_active") and user.is_active is False:
        await record_login(
            db, user_id=user.id, email=user.email, method="password",
            outcome="deactivated", ip=ip, user_agent=ua,
        )
        await db.commit()
        raise HTTPException(403, "Account is deactivated. Contact your administrator.")

    if not verify_password(payload.password, user.hashed_pw):
        lockout.on_failure(user)
        await record_login(
            db, user_id=user.id, email=user.email, method="password",
            outcome="invalid_password", ip=ip, user_agent=ua,
        )
        await db.commit()
        remaining = max(0, lockout.MAX_FAILED - (user.failed_login_count or 0))
        detail = "Invalid email or password"
        if remaining <= 2 and remaining > 0:
            detail += f" ({remaining} attempt(s) left before lockout)"
        elif remaining == 0:
            detail = (
                f"Too many failed attempts — account locked for "
                f"{lockout.LOCK_MINUTES} minutes"
            )
        raise HTTPException(401, detail)

    # If 2FA is enabled, require a valid TOTP code alongside the password.
    if getattr(user, "totp_enabled", False):
        from app.services.totp import verify_totp
        from app.models.backup_code import BackupCode
        from sqlalchemy import select as sa_select

        if not payload.totp_code:
            raise HTTPException(428, "TOTP code required")

        code = payload.totp_code.strip()
        code_ok = False

        # 1. Try TOTP first (6 digits from authenticator app).
        if len(code) == 6 and code.isdigit() and verify_totp(user.totp_secret or "", code):
            code_ok = True

        # 2. Else try backup code (format XXXXX-XXXXX, 11 chars incl. dash).
        if not code_ok and len(code) >= 8:
            rows = (await db.execute(
                sa_select(BackupCode).where(
                    BackupCode.user_id == user.id,
                    BackupCode.used_at.is_(None),
                )
            )).scalars().all()
            for bc in rows:
                if verify_password(code, bc.code_hash):
                    bc.used_at = datetime.now(tz=timezone.utc)
                    code_ok = True
                    break

        if not code_ok:
            lockout.on_failure(user)
            await record_login(
                db, user_id=user.id, email=user.email, method="totp",
                outcome="invalid_totp", ip=ip, user_agent=ua,
            )
            await db.commit()
            raise HTTPException(401, "Invalid TOTP or backup code")

    # Success — reset the failure counter and issue tokens.
    lockout.on_success(user)
    await record_login(
        db, user_id=user.id, email=user.email, method="password",
        outcome="success", ip=ip, user_agent=ua,
    )
    # Anomaly detection AFTER recording the event so history is fresh.
    try:
        anomaly = await check_anomaly(db, user_id=user.id, ip=ip)
        if anomaly is not None:
            await notify_admin(user.email, anomaly, ip)
    except Exception:  # noqa: BLE001
        pass

    access = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    refresh = create_refresh_token(user_id=user.id, org_id=user.org_id, role=user.role)
    # R16: record the session for device management.
    from app.services.session_tracker import record_session
    await record_session(db, refresh_token=refresh, ip=ip, user_agent=ua)
    await db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_expire_min * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    from app.services.rate_limit import check_login_rate

    # Same IP budget applies to refresh — prevents high-frequency token grinding.
    await check_login_rate(request)
    """Exchange a valid refresh token for a fresh access+refresh pair.

    - Rejects access tokens (typ mismatch)
    - Rejects revoked jti (revocation list check)
    - Re-fetches the user to catch role / org / is_active changes
    - Issues a **new refresh token** — token rotation reduces replay window
    - Revokes the old refresh jti (single-use enforcement)
    """
    try:
        claims = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid or expired refresh token")
    if claims.get("typ") != "refresh":
        raise HTTPException(401, "Not a refresh token")

    # Revocation check.
    old_jti = claims.get("jti")
    if old_jti:
        r = await db.execute(
            select(RevokedToken).where(RevokedToken.jti == old_jti)
        )
        if r.scalar_one_or_none() is not None:
            raise HTTPException(401, "Refresh token has been revoked")

    try:
        user_id = UUID(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(401, "Malformed refresh token")

    r = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "User not found")
    if hasattr(user, "is_active") and user.is_active is False:
        raise HTTPException(403, "Account is deactivated")

    # Revoke the old refresh token — single use rotation.
    if old_jti:
        exp_ts = claims.get("exp")
        db.add(RevokedToken(
            jti=old_jti,
            exp=datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            if exp_ts else datetime.now(tz=timezone.utc),
            reason="rotated",
        ))

    access = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    new_refresh = create_refresh_token(
        user_id=user.id, org_id=user.org_id, role=user.role
    )
    # R16: rotate session record (old jti already revoked above).
    from app.services.session_tracker import touch_or_rotate_session
    ua_r = request.headers.get("user-agent") if request else None
    ip_r = request.client.host if (request and request.client) else None
    await touch_or_rotate_session(
        db, old_jti=old_jti or "", new_refresh_token=new_refresh,
        ip=ip_r, user_agent=ua_r,
    )
    await db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=settings.jwt_expire_min * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
async def logout(
    payload: RefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the caller's refresh token — server-side session termination.

    Body: {refresh_token: "..."}. The access token is short-lived so we
    only revoke the refresh; any subsequent /auth/refresh with this jti
    will 401. Access tokens naturally expire in ≤60 min.
    """
    try:
        claims = decode_token(payload.refresh_token)
    except Exception:
        # Silently succeed — token was invalid anyway, treat as logged out.
        return {"ok": True, "revoked": False, "reason": "invalid_token"}
    if claims.get("typ") != "refresh":
        return {"ok": True, "revoked": False, "reason": "not_refresh"}
    # Only allow revoking own tokens.
    if claims.get("sub") != str(user.id):
        raise HTTPException(403, "Cannot revoke another user's token")
    jti = claims.get("jti")
    if not jti:
        return {"ok": True, "revoked": False, "reason": "no_jti"}
    # Idempotent: check if already revoked.
    r = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
    if r.scalar_one_or_none() is not None:
        return {"ok": True, "revoked": True, "already": True}
    exp_ts = claims.get("exp")
    db.add(RevokedToken(
        jti=jti,
        exp=datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        if exp_ts else datetime.now(tz=timezone.utc),
        reason="logout",
    ))
    await db.commit()
    return {"ok": True, "revoked": True}


@router.post("/password")
async def change_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Self-service password change for the logged-in user."""
    if not verify_password(payload.old_password, user.hashed_pw):
        raise HTTPException(400, "Old password is incorrect")
    if payload.old_password == payload.new_password:
        raise HTTPException(400, "New password must differ from old")
    try:
        validate_password(payload.new_password, email=user.email)
    except PasswordPolicyError as e:
        raise HTTPException(400, str(e))
    user.hashed_pw = hash_password(payload.new_password)
    # R16: revoke sibling sessions (keep current session alive via jti).
    try:
        from app.services.session_tracker import revoke_by_jti
        # Find current session jti to keep it alive.
        auth_hdr = ""  # can't easily reach request here without dependency; fall back to revoking ALL
        from sqlalchemy import select as _sel
        from app.models.active_session import ActiveSession as _AS
        _now = datetime.now(tz=timezone.utc)
        rows = (await db.execute(
            _sel(_AS).where(_AS.user_id == user.id, _AS.revoked_at.is_(None))
        )).scalars().all()
        revoked = 0
        for r in rows:
            r.revoked_at = _now
            db.add(RevokedToken(jti=r.jti, exp=_now, reason="password_change"))
            revoked += 1
    except Exception:  # noqa: BLE001
        revoked = 0
    await db.commit()
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
