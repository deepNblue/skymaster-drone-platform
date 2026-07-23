"""Approval-as-a-Service — R21 Step E · outbound approval webhook layer.

Turns SkyMaster into a reverse-facing "one-click compliance" partner for
authorities (UOM / local police / ATC / civil aviation) that want to
consume approval events over HTTPS instead of polling.

Data model
----------

* ``AaasClient``   — a subscribing authority (name, callback URL, HMAC secret,
                    subscribed event types, active flag).
* ``AaasDelivery`` — per-event delivery attempt (client × event × status),
                    with retry count, next_attempt_at, response snippet.

Event shape (JSON body posted to the client's ``callback_url``):

::

    {
      "event": "approval.submitted",
      "event_id": "<uuid4>",
      "sent_at": "2026-07-10T14:57:00Z",
      "approval": {
        "id": "...", "title": "...", "category": "special",
        "planned_start": "...", "planned_end": "...", "region": "...",
        "aircraft_reg": "...", "pilot_name": "...", "pilot_license": "...",
        "status": "submitted"
      }
    }

Every request carries these HTTP headers so the recipient can verify:

* ``X-AaaS-Event``     — event type (approval.submitted / approved / …)
* ``X-AaaS-Event-ID``  — event UUID (used for idempotency dedup)
* ``X-AaaS-Timestamp`` — ISO-8601 UTC send time
* ``X-AaaS-Signature`` — hex HMAC-SHA256 of ``timestamp + "." + body``

Design principles
-----------------

1. **Non-blocking to core flight ops.** Publishing runs after the DB
   commit and never raises to the API caller.
2. **At-least-once, retriable.** Every attempt writes a row; failures
   schedule a next_attempt_at with exponential backoff (up to 6 tries).
3. **Signed but not encrypted.** HMAC ensures authenticity; the callback
   URL is expected to be HTTPS, so confidentiality is TLS's job.
4. **Deterministic surface.** No LLM, no external SDK. Standard library
   ``urllib`` only.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public event vocabulary — kept small and deterministic.
# ---------------------------------------------------------------------------

APPROVAL_EVENTS = (
    "approval.submitted",
    "approval.authority.accepted",
    "approval.authority.approved",
    "approval.authority.rejected",
    "approval.approved",
    "approval.rejected",
    "approval.cancelled",
    "approval.flown",
)


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``timestamp + "." + body`` — same shape as Stripe."""
    mac = hmac.new(
        secret.encode("utf-8"),
        msg=(timestamp + ".").encode("utf-8") + body,
        digestmod=hashlib.sha256,
    )
    return mac.hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """Constant-time signature check for the receiving side."""
    expected = sign_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def new_client_secret() -> str:
    """Generate a URL-safe 40-char shared secret."""
    return secrets.token_urlsafe(30)


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def build_approval_event(event: str, approval: Any) -> dict:
    """Compact JSON body for an approval-lifecycle event."""
    return {
        "event": event,
        "event_id": str(uuid4()),
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "approval": {
            "id": str(approval.id),
            "title": approval.title,
            "category": approval.category,
            "status": approval.status,
            "planned_start": _iso(
                getattr(approval, "planned_start", None)
                or getattr(approval, "start_ts", None)
            ),
            "planned_end": _iso(
                getattr(approval, "planned_end", None)
                or getattr(approval, "end_ts", None)
            ),
            "aircraft_reg": approval.aircraft_reg,
            "pilot_name": approval.pilot_name,
            "pilot_license": approval.pilot_license,
            "region": getattr(approval, "region", None),
            "mission_id": (
                str(approval.mission_id) if getattr(approval, "mission_id", None) else None
            ),
        },
    }


# ---------------------------------------------------------------------------
# Delivery — HTTP POST wrapped in the executor
# ---------------------------------------------------------------------------


def _deliver_sync(
    url: str, body: bytes, headers: dict[str, str], timeout_s: float,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = resp.getcode() or 0
            text = resp.read(4096).decode(errors="replace")
            return code, text
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read(2048).decode(errors="replace") if exc.fp else str(exc)
        except Exception:
            text = str(exc)
        return exc.code, text
    except Exception as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


async def deliver_event(
    *,
    url: str,
    secret: str,
    event: str,
    payload: dict,
    timeout_s: float = 5.0,
) -> tuple[int, str, str]:
    """POST an event to a subscriber. Returns (status_code, response_body, signature)."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ts = payload.get("sent_at") or datetime.now(timezone.utc).isoformat()
    sig = sign_payload(secret, ts, body)
    headers = {
        "Content-Type": "application/json",
        "X-AaaS-Event": event,
        "X-AaaS-Event-ID": payload.get("event_id", ""),
        "X-AaaS-Timestamp": ts,
        "X-AaaS-Signature": sig,
        "User-Agent": "SkyMaster-AaaS/1.0",
    }
    loop = asyncio.get_running_loop()
    code, text = await loop.run_in_executor(
        None, _deliver_sync, url, body, headers, timeout_s,
    )
    return code, text, sig


# ---------------------------------------------------------------------------
# Fan-out — pick subscribers, record deliveries, best-effort dispatch
# ---------------------------------------------------------------------------


async def fanout_approval_event(
    session: AsyncSession, *, event: str, approval: Any,
) -> list[UUID]:
    """Deliver ``event`` for ``approval`` to every matching AaasClient.

    Returns the list of AaasDelivery IDs created. Never raises.
    """
    from app.models.aaas import AaasClient, AaasDelivery

    payload = build_approval_event(event, approval)
    q = select(AaasClient).where(AaasClient.active.is_(True))
    result = await session.execute(q)
    clients = list(result.scalars().all())

    delivery_ids: list[UUID] = []
    for client in clients:
        # Filter — empty ``events`` field means "all events".
        events_list = client.events or []
        if events_list and event not in events_list:
            continue

        delivery = AaasDelivery(
            client_id=client.id,
            event=event,
            event_id=UUID(payload["event_id"]),
            approval_id=approval.id,
            payload=payload,
            attempts=0,
            status="pending",
        )
        session.add(delivery)
        await session.flush()
        delivery_ids.append(delivery.id)

        # Attempt one delivery inline (still non-blocking to caller).
        try:
            code, text, sig = await deliver_event(
                url=client.callback_url,
                secret=client.secret,
                event=event,
                payload=payload,
            )
        except Exception as exc:  # pragma: no cover
            code, text, sig = 0, f"unexpected: {exc}", ""

        delivery.attempts = 1
        delivery.last_status_code = code
        delivery.last_response = (text or "")[:2000]
        delivery.last_signature = sig
        delivery.last_attempt_at = datetime.now(timezone.utc)
        if 200 <= code < 300:
            delivery.status = "delivered"
            delivery.next_attempt_at = None
        else:
            delivery.status = "retrying"
            # exponential backoff: 30 s, 2m, 5m, 15m, 1h, 6h
            backoff = [30, 120, 300, 900, 3600, 21600]
            delivery.next_attempt_at = datetime.now(timezone.utc).replace(
                microsecond=0,
            ) + _delta(backoff[min(delivery.attempts - 1, len(backoff) - 1)])

    return delivery_ids


def _delta(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Retry sweep — invoked by admin endpoint or a cron job
# ---------------------------------------------------------------------------


MAX_ATTEMPTS = 6


async def retry_due_deliveries(session: AsyncSession, *, limit: int = 50) -> dict:
    """Re-attempt all deliveries whose ``next_attempt_at`` has passed.

    Returns a summary dict — safe to expose via admin endpoint.
    """
    from app.models.aaas import AaasClient, AaasDelivery

    now = datetime.now(timezone.utc)
    q = (
        select(AaasDelivery)
        .where(AaasDelivery.status == "retrying")
        .where(AaasDelivery.next_attempt_at <= now)
        .where(AaasDelivery.attempts < MAX_ATTEMPTS)
        .order_by(AaasDelivery.next_attempt_at.asc())
        .limit(limit)
    )
    rows = list((await session.execute(q)).scalars().all())
    summary = {"considered": len(rows), "delivered": 0, "retried": 0, "failed": 0}

    for d in rows:
        client = await session.get(AaasClient, d.client_id)
        if client is None or not client.active:
            d.status = "abandoned"
            d.next_attempt_at = None
            summary["failed"] += 1
            continue
        try:
            code, text, sig = await deliver_event(
                url=client.callback_url,
                secret=client.secret,
                event=d.event,
                payload=d.payload,
            )
        except Exception as exc:  # pragma: no cover
            code, text, sig = 0, f"unexpected: {exc}", ""

        d.attempts = (d.attempts or 0) + 1
        d.last_status_code = code
        d.last_response = (text or "")[:2000]
        d.last_signature = sig
        d.last_attempt_at = datetime.now(timezone.utc)

        if 200 <= code < 300:
            d.status = "delivered"
            d.next_attempt_at = None
            summary["delivered"] += 1
        elif d.attempts >= MAX_ATTEMPTS:
            d.status = "failed"
            d.next_attempt_at = None
            summary["failed"] += 1
        else:
            d.status = "retrying"
            backoff = [30, 120, 300, 900, 3600, 21600]
            d.next_attempt_at = now + _delta(backoff[min(d.attempts - 1, len(backoff) - 1)])
            summary["retried"] += 1
    return summary
