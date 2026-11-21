"""Authentication service — password hashing + JWT issuance/decoding.

Uses ``bcrypt`` directly (not passlib) to avoid the known passlib<1.7.5
+ bcrypt>=4.1 incompatibility.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from uuid import uuid4
from app.config import settings

_BCRYPT_MAX = 72


def _clamp(pw: str) -> bytes:
    return pw.encode("utf-8")[:_BCRYPT_MAX]


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(_clamp(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if the plaintext matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(_clamp(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: UUID | str,
    org_id: UUID | str | None,
    role: str,
    expires_min: int | None = None,
) -> str:
    """Create a signed JWT access token.

    Payload: {sub, org_id, role, typ:"access", exp, iat}
    """
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=expires_min or settings.jwt_expire_min)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id) if org_id is not None else None,
        "role": role,
        "typ": "access",
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_refresh_token(
    user_id: UUID | str,
    org_id: UUID | str | None,
    role: str,
    expires_days: int | None = None,
) -> str:
    """Create a long-lived refresh token.

    Payload: {sub, org_id, role, typ:"refresh", jti, exp, iat}

    Refresh tokens live longer (default 14 days vs 60 min for access) and
    are the only tokens the /auth/refresh endpoint accepts. Access tokens
    are rejected there — enforces separation of concerns.
    """
    now = datetime.now(tz=timezone.utc)
    days = expires_days or getattr(settings, "jwt_refresh_days", 14)
    expire = now + timedelta(days=days)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id) if org_id is not None else None,
        "role": role,
        "typ": "refresh",
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict[str, Any]:
    """Decode & verify a JWT. Raises JWTError on failure."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except JWTError:
        raise
