"""Record & rotate ActiveSession rows from freshly issued refresh tokens."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.active_session import ActiveSession
from app.services.auth import decode_token

logger = logging.getLogger(__name__)


def _device_label(ua: Optional[str]) -> Optional[str]:
    if not ua:
        return None
    u = ua.lower()
    if "iphone" in u: return "iPhone"
    if "ipad" in u: return "iPad"
    if "android" in u: return "Android"
    if "windows" in u:
        if "chrome" in u: return "Windows · Chrome"
        if "edg/" in u or "edge" in u: return "Windows · Edge"
        if "firefox" in u: return "Windows · Firefox"
        return "Windows"
    if "macintosh" in u or "mac os" in u:
        if "safari" in u and "chrome" not in u: return "macOS · Safari"
        if "chrome" in u: return "macOS · Chrome"
        return "macOS"
    if "linux" in u: return "Linux"
    return "Unknown"


async def record_session(
    session: AsyncSession,
    *,
    refresh_token: str,
    ip: Optional[str],
    user_agent: Optional[str],
    country: Optional[str] = None,
) -> Optional[ActiveSession]:
    """Insert an ActiveSession row for a freshly minted refresh token."""
    try:
        claims = decode_token(refresh_token)
        jti = claims.get("jti")
        user_id = claims.get("sub")
        if not jti or not user_id:
            return None
        row = ActiveSession(
            user_id=UUID(user_id) if isinstance(user_id, str) else user_id,
            jti=jti,
            ip=ip,
            country=country,
            user_agent=(user_agent or "")[:512] or None,
            device_label=_device_label(user_agent),
        )
        session.add(row)
        return row
    except Exception:  # noqa: BLE001
        logger.debug("record_session skipped", exc_info=True)
        return None


async def touch_or_rotate_session(
    session: AsyncSession,
    *,
    old_jti: str,
    new_refresh_token: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> Optional[ActiveSession]:
    """On refresh rotation, mark the old session revoked & create new one.

    Preserves the "device continuity" — new session gets same device_label
    unless UA has changed.
    """
    try:
        # Mark old session as revoked (soft-delete for audit).
        await session.execute(
            update(ActiveSession)
            .where(ActiveSession.jti == old_jti)
            .values(revoked_at=datetime.now(tz=timezone.utc))
        )
        return await record_session(
            session,
            refresh_token=new_refresh_token,
            ip=ip,
            user_agent=user_agent,
        )
    except Exception:  # noqa: BLE001
        logger.debug("touch_or_rotate_session skipped", exc_info=True)
        return None


async def revoke_by_jti(session: AsyncSession, jti: str) -> None:
    """Mark a session revoked (called on logout)."""
    try:
        await session.execute(
            update(ActiveSession)
            .where(ActiveSession.jti == jti)
            .values(revoked_at=datetime.now(tz=timezone.utc))
        )
    except Exception:  # noqa: BLE001
        logger.debug("revoke_by_jti skipped", exc_info=True)
