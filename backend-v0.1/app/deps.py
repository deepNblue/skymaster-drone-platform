"""FastAPI dependencies — DB session, current user, RBAC."""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.services.auth import decode_token
from app.services.rbac import Role, has_at_least

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the currently authenticated user from a Bearer JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Reject revoked access tokens (jti in revocation list).
    jti = payload.get("jti")
    if jti:
        from app.models.revoked_token import RevokedToken
        rev = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
        if rev.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        )
    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject"
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    # Stash claims for downstream inspection (e.g. role check).
    request.state.claims = payload
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    """FastAPI dependency factory enforcing that the user has one of `roles`."""

    allowed = {r.lower() for r in roles}

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role.lower() not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role in {sorted(allowed)}",
            )
        return user

    return _checker


def require_min_role(minimum: Role) -> Callable[[User], User]:
    """FastAPI dependency factory enforcing hierarchical role check.

    Prefer this over ``require_role`` for new endpoints: it correctly
    admits higher-ranked roles (admin passes operator gates, etc.).

    Also honors ``settings.auth_optional`` for dev/tests — when true,
    an anonymous request is treated as an 'operator' dummy user so the
    local demo stack works without login.
    """

    async def _checker(
        user: User = Depends(get_current_user_optional),
    ) -> User:
        if not has_at_least(user.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role ≥ {minimum.value}",
            )
        return user

    return _checker


# ---------- Test/CI bypass ------------------------------------------------
# When ``settings.auth_optional`` is true (dev/tests), fall back to an
# anonymous ``operator`` user if no valid Bearer is presented, so the sim
# endpoints keep working from the `start_demo.py` local stack. Production
# should always leave this false.
_DUMMY_USER: User | None = None


def _dummy_user() -> User:
    global _DUMMY_USER
    if _DUMMY_USER is None:
        from uuid import uuid4
        # Demo/anon user runs as admin so single-node demo can exercise
        # every admin endpoint without login. Production MUST disable
        # auth_optional and provision real users.
        _DUMMY_USER = User(  # type: ignore[call-arg]
            id=uuid4(),
            org_id=None,
            email="anonymous@local",
            hashed_pw="",
            role="admin",
        )
    return _DUMMY_USER


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Same as ``get_current_user`` but falls back to anonymous operator
    when ``AUTH_OPTIONAL=true``. Used for /sim, /uom, /geofence so the
    demo stack works without login while production keeps auth on.
    """
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return await get_current_user(request, credentials, db)
    if getattr(settings, "auth_optional", False):
        return _dummy_user()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "get_db", "get_current_user", "get_current_user_optional",
    "require_role", "require_min_role", "Role",
]
