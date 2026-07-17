"""Anomalous-login detector — flags "new IP" and "impossible travel" events.

Design goals:
    - Cheap: single SELECT bounded by 30-day window
    - No PII: only IP + country stored, no location
    - Best-effort geoip: uses a tiny built-in CIDR heuristic when no db;
      integrations (MaxMind, IPinfo) can be added by monkeypatching
      ``geoip_lookup``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func

from app.models.login_event import LoginEvent

logger = logging.getLogger(__name__)

# ---- GeoIP -----------------------------------------------------------------


def geoip_lookup(ip: str | None) -> str | None:
    """Return an ISO-3166 alpha-2 country code, or None if unknown.

    Default heuristic: known-CN ranges → "CN", else None. Meant to be
    monkeypatched with a real MaxMind lookup in production.
    """
    if not ip:
        return None
    if ip.startswith(("10.", "192.168.", "127.", "172.16.", "::1")):
        return "LAN"
    # Very small demo — enough to trip "new country" alerts in tests.
    if ip.startswith(("1.0.", "1.1.", "36.", "39.", "42.", "58.", "60.", "61.")):
        return "CN"
    if ip.startswith(("203.", "8.8.")):
        return "US"
    return None


# ---- Detector --------------------------------------------------------------


async def check_anomaly(
    session, *, user_id, ip: str | None
) -> Optional[dict]:
    """Return ``{"reason": "...", "detail": {...}}`` if this login looks
    anomalous vs the user's recent history, else None.

    Rules:
        1. NEW_IP     — user has never logged in successfully from this IP
        2. NEW_COUNTRY — country differs from any of user's last-30d logins
        3. IMPOSSIBLE_TRAVEL — last successful login <5 min ago from a
           different country (impossible physical travel window)
    """
    if user_id is None or not ip:
        return None

    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=30)

    stmt = (
        select(LoginEvent)
        .where(
            LoginEvent.user_id == user_id,
            LoginEvent.outcome == "success",
            LoginEvent.created_at >= since,
        )
        .order_by(LoginEvent.created_at.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        # First-ever success — not anomalous.
        return None

    current_country = geoip_lookup(ip)
    seen_ips = {r.ip for r in rows if r.ip}
    seen_countries = {r.country for r in rows if r.country}

    if ip not in seen_ips:
        # New IP is suspicious but common (mobile networks change IP).
        # Only escalate when the country is also new.
        if current_country and current_country not in seen_countries:
            return {
                "reason": "NEW_COUNTRY",
                "detail": {
                    "current": current_country,
                    "recent": sorted(c for c in seen_countries if c),
                    "ip": ip,
                },
            }

        # Impossible travel: last successful login was very recent
        # from a *different* country.
        last = rows[0]
        if (
            last.country
            and current_country
            and last.country != current_country
            and (now - last.created_at) < timedelta(minutes=5)
        ):
            return {
                "reason": "IMPOSSIBLE_TRAVEL",
                "detail": {
                    "from": last.country,
                    "to": current_country,
                    "gap_minutes": int((now - last.created_at).total_seconds() / 60),
                },
            }

        # Fall-through: new IP but same country — soft-warn only.
        return {
            "reason": "NEW_IP",
            "detail": {"ip": ip, "country": current_country},
        }

    return None


# ---- Notifier hook ---------------------------------------------------------


async def notify_admin(email: str, anomaly: dict, ip: str | None) -> None:
    """Best-effort admin/user notification.

    Reads ``ANOMALY_WEBHOOK_URL`` env (POST JSON body) — if unset, only logs.
    """
    payload = {
        "type": "login_anomaly",
        "email": email,
        "ip": ip,
        "reason": anomaly["reason"],
        "detail": anomaly.get("detail", {}),
    }
    logger.warning("LOGIN_ANOMALY %s", payload)
    url = os.getenv("ANOMALY_WEBHOOK_URL")
    if not url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Anomaly webhook failed: %s", exc)
