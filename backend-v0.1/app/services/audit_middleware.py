"""Audit-log middleware — v2.0/等保 track.

Captures every mutating HTTP request (POST/PUT/PATCH/DELETE) plus every
successful login, and appends a row to ``audit_logs``.

Design:
  - Runs after the request is processed so we can capture status code.
  - Silent-fails on DB errors (audit should never break the app).
  - Skips ``/health`` and read-only GETs.
  - Bearer token is decoded lazily to extract ``actor_id`` (falls back
    to ``None`` for anonymous).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PATHS = {"/api/v1/health", "/health", "/api/v1/ws/telemetry", "/api/v1/ws/events"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Fast path — don't audit uninteresting requests.
        should_audit = request.method in _MUTATING and not any(
            request.url.path.startswith(p) for p in _SKIP_PATHS
        )

        start = time.time()
        response = await call_next(request)
        if not should_audit:
            return response

        # Fire-and-forget: schedule the log write.
        try:
            actor_id, actor_role = _extract_actor(request)
            ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent")
            duration_ms = int((time.time() - start) * 1000)
            diff = {
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "query": dict(request.query_params) or None,
            }
            await _write_audit(
                request.app.state,
                actor_id=actor_id,
                actor_role=actor_role,
                action=f"{request.method} {request.url.path}",
                resource=request.url.path,
                diff=diff,
                ip=ip,
                ua=ua,
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit write skipped", exc_info=True)
        return response


def _extract_actor(request: Request) -> tuple[UUID | None, str | None]:
    """Decode Bearer JWT (best-effort) to extract user_id + role."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[7:]
    try:
        from app.services.auth import decode_token  # local import
        payload = decode_token(token)
        sub = payload.get("sub")
        role = payload.get("role")
        return (UUID(sub) if sub else None), role
    except Exception:  # noqa: BLE001
        return None, None


async def _write_audit(
    app_state,
    *,
    actor_id: UUID | None,
    actor_role: str | None = None,
    action: str,
    resource: str | None,
    diff: dict,
    ip: str | None,
    ua: str | None,
) -> None:
    """Best-effort audit persistence.

    Priority order:
      1. If ``app_state.audit_sink`` is set (test hook), append to it.
      2. Else try SQLAlchemy write via ``app_state.async_sessionmaker``.
      3. Else emit a structured log line (last-resort file audit).
    """
    sink = getattr(app_state, "audit_sink", None)
    if sink is not None:
        sink.append({
            "actor_id": str(actor_id) if actor_id else None,
            "actor_role": actor_role,
            "action": action, "resource": resource,
            "diff": diff, "ip": ip, "ua": ua,
            "ts": time.time(),
        })
        _bump_audit_metric(action, actor_role)
        return

    session_factory = getattr(app_state, "async_sessionmaker", None)
    if session_factory is not None:
        try:
            import json as _json
            from sqlalchemy import select as _sel
            from app.models.audit_log import AuditLog
            from app.services.crypto_gateway import gm

            async with session_factory() as session:
                # --- R18: extend tamper-evident hash chain ------------------
                prev_hex: str | None = None
                curr_hex: str | None = None
                diff_ct: str | None = None
                stored_diff = diff
                if gm.enabled_for("audit_log"):
                    # Pull previous chain head. In production add an index or
                    # a separate `audit_chain_head` singleton row; for now
                    # ORDER BY id DESC LIMIT 1 is fine for MVP volumes.
                    row_prev = (await session.execute(
                        _sel(AuditLog.curr_hash)
                        .where(AuditLog.curr_hash.isnot(None))
                        .order_by(AuditLog.id.desc())
                        .limit(1)
                    )).scalar_one_or_none()
                    prev_hex = row_prev or ("0" * 64)
                    payload = _json.dumps(
                        {"a": action, "r": resource, "d": diff, "act": str(actor_id)},
                        sort_keys=True, ensure_ascii=False,
                    )
                    curr_hex = gm.chain_hash(
                        bytes.fromhex(prev_hex), payload, module="audit_log",
                    ).hex()
                    if gm.mode == "full" and diff is not None:
                        # Store ciphertext, blank out plaintext diff.
                        diff_ct = gm.encrypt(
                            "audit_log", _json.dumps(diff, ensure_ascii=False),
                        )  # type: ignore[assignment]
                        stored_diff = None

                row = AuditLog(
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action=action,
                    resource=resource,
                    diff=stored_diff,
                    ip=ip,
                    ua=ua,
                    prev_hash=prev_hex,
                    curr_hash=curr_hex,
                    diff_ct=diff_ct,
                )
                # R21 F: SM2 non-repudiation signature over curr_hash.
                # Soft-fail — signing is best-effort so it can never
                # block the audit write.
                try:
                    from app.services.sm2_signer import sign_hash
                    from datetime import datetime, timezone
                    ts_iso = datetime.now(timezone.utc).isoformat()
                    signed = sign_hash(
                        record_id=f"audit:{action}:{resource or ''}",
                        curr_hash=curr_hex,
                        ts=ts_iso,
                    )
                    if signed:
                        row.sig_hex, row.sig_key_id = signed
                except Exception:  # pragma: no cover
                    pass
                session.add(row)
                await session.commit()
            _bump_audit_metric(action, actor_role)
            return
        except Exception:  # noqa: BLE001
            pass

    # Fallback: emit as JSON log line.
    logger.info(
        "AUDIT %s",
        json.dumps({
            "actor_id": str(actor_id) if actor_id else None,
            "actor_role": actor_role,
            "action": action, "resource": resource,
            "ip": ip, "ua": ua,
            "diff": diff,
        }),
    )
    _bump_audit_metric(action, actor_role)


def _bump_audit_metric(action: str, actor_role: str | None) -> None:
    """Increment Prometheus audit counter — safe to call w/o metrics registered."""
    try:
        from app.services.metrics import AUDIT_EVENTS
        method = action.split(" ", 1)[0] if " " in action else action
        AUDIT_EVENTS.inc(actor_role=actor_role or "anonymous", method=method)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------- test-only in-memory sink
class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def append(self, ev: dict) -> None:
        self.events.append(ev)

    def by_action(self, prefix: str) -> list[dict]:
        return [e for e in self.events if e["action"].startswith(prefix)]
