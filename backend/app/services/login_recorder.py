"""Helper to persist LoginEvent rows without breaking auth if DB fails."""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from app.models.login_event import LoginEvent
from app.services.anomaly_detector import geoip_lookup

logger = logging.getLogger(__name__)


async def record_login(
    session,
    *,
    user_id: Optional[UUID],
    email: Optional[str],
    method: str,
    outcome: str,
    ip: Optional[str],
    user_agent: Optional[str],
    extra: Optional[dict] = None,
) -> Optional[LoginEvent]:
    """Insert a login_events row (best-effort). Never raises on DB error."""
    try:
        row = LoginEvent(
            user_id=user_id,
            email=email,
            method=method,
            outcome=outcome,
            ip=ip,
            country=geoip_lookup(ip),
            user_agent=(user_agent or "")[:512] or None,
            extra=extra,
        )
        session.add(row)
        # NOTE: we don't commit here — the caller's transaction owns commit.
        return row
    except Exception:  # noqa: BLE001
        logger.debug("record_login skipped", exc_info=True)
        return None


def client_ip_from_request(request) -> Optional[str]:
    xff = request.headers.get("x-forwarded-for") if request else None
    if xff:
        return xff.split(",")[0].strip()
    if request and request.client:
        return request.client.host
    return None
