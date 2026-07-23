"""WebSocket telemetry endpoint — fans out Redis pub/sub to browser clients.

SkyMaster v0.1 W4 (SDD §5.2):

    telemetry_consumer  →  redis pub/sub: telemetry.broadcast.{drone_id}
                                                     │
                                                     v
                                            /ws/telemetry/{drone_id}
                                                     │
                                                     v
                                                 browser
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from starlette.websockets import WebSocketState

from app.services.auth import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ------ tuning knobs (module-level so tests can monkeypatch) ---------------
HEARTBEAT_INTERVAL_S = 30.0
REDIS_RECONNECT_BASE_S = 1.0
REDIS_RECONNECT_MAX_S = 30.0

# ------ frame rate-limit — burst pigeon-hole ------------------------------
# Cap browser-bound frames to N per second per socket (per drone_id or
# global events). This blunts the burst amplification when a drone
# briefly floods telemetry (e.g. 200 Hz IMU) — the client would drop them
# anyway, so we drop server-side to save bandwidth.
WS_RATE_LIMIT_HZ = 20  # 20 frames/s per socket == 1 every 50ms


def _ws_metric_inc(channel: str) -> None:
    """Increment gauge for open WS on the given channel."""
    try:
        from app.services.metrics import WS_CONNECTIONS, WS_ACTIVE
        WS_CONNECTIONS.inc(channel=channel)
        WS_ACTIVE.inc()
    except Exception:  # noqa: BLE001
        pass


def _ws_metric_dec(channel: str) -> None:
    """Decrement gauge — must exactly mirror _ws_metric_inc on close."""
    try:
        from app.services.metrics import WS_CONNECTIONS, WS_ACTIVE
        WS_CONNECTIONS.dec(channel=channel)
        WS_ACTIVE.dec()
    except Exception:  # noqa: BLE001
        pass


async def _get_pubsub(app_state: object, channel: str):
    """Create a pubsub object subscribed to ``channel`` from app.state.redis."""
    redis = getattr(app_state, "redis", None)
    if redis is None:
        raise RuntimeError(
            "app.state.redis is not configured — WS telemetry requires the "
            "Redis client to be initialized in the FastAPI lifespan."
        )
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    return pubsub


async def _heartbeat(websocket: WebSocket) -> None:
    """Send an application-level ping every ``HEARTBEAT_INTERVAL_S`` seconds."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        return
    except asyncio.CancelledError:
        raise


async def _pump_pubsub(websocket: WebSocket, app_state: object, channel: str) -> None:
    """Loop: subscribe → forward messages → reconnect on failure.

    Handles transient Redis errors with exponential backoff. Exits when the
    WebSocket is no longer connected or the task is cancelled. Frames are
    rate-limited to ``WS_RATE_LIMIT_HZ`` per second; excess frames are
    dropped (last-write-wins semantics preferred for telemetry).
    """
    import time as _time
    backoff = REDIS_RECONNECT_BASE_S
    min_interval = 1.0 / max(WS_RATE_LIMIT_HZ, 1)
    last_sent = 0.0
    while websocket.client_state == WebSocketState.CONNECTED:
        pubsub = None
        try:
            pubsub = await _get_pubsub(app_state, channel)
            backoff = REDIS_RECONNECT_BASE_S

            while websocket.client_state == WebSocketState.CONNECTED:
                # ignore_subscribe_messages=False → we filter by ["type"] below.
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                # Rate limit — drop frames past ceiling
                now = _time.monotonic()
                if now - last_sent < min_interval:
                    continue
                last_sent = now
                data = message.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", errors="replace")
                try:
                    payload = json.loads(data) if isinstance(data, str) else data
                except json.JSONDecodeError:
                    payload = {"raw": data}
                await websocket.send_json(
                    {
                        "type": (payload.get("type") if isinstance(payload, dict) else None) or "telemetry",
                        "ts": payload.get("ts") if isinstance(payload, dict) else None,
                        "data": payload,
                    }
                )
        except asyncio.CancelledError:
            raise
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:  # noqa: BLE001 — Redis or transport error
            logger.exception(
                "Redis pubsub error on %s; reconnecting in %.1fs", channel, backoff
            )
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(backoff * 2, REDIS_RECONNECT_MAX_S)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:  # noqa: BLE001
                    logger.debug("pubsub cleanup swallowed", exc_info=True)


@router.websocket("/ws/events")
async def events_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Push global events (mission.completed, etc.) to the browser.

    Currently subscribes to Redis channel ``mission.event.all``.
    """
    if token is not None:
        try:
            decode_token(token)
        except JWTError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="invalid token"
            )
            return

    await websocket.accept()
    channel = "mission.event.all"
    _ws_metric_inc("events")

    pump_task = asyncio.create_task(
        _pump_pubsub(websocket, websocket.app.state, channel),
        name="ws-events-pump",
    )
    hb_task = asyncio.create_task(_heartbeat(websocket), name="ws-events-hb")

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        _ws_metric_dec("events")
        for task in (pump_task, hb_task):
            task.cancel()
        for task in (pump_task, hb_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except RuntimeError:
                pass


@router.websocket("/ws/telemetry/{drone_id}")
async def telemetry_ws(
    websocket: WebSocket,
    drone_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Stream telemetry for a drone via Redis pub/sub fan-out.

    Query params
    ------------
    token : optional JWT. If provided it is validated via
        :func:`app.services.auth.decode_token`. Invalid tokens close the
        socket with 4401 (policy violation).
    """
    if token is not None:
        try:
            decode_token(token)
        except JWTError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="invalid token"
            )
            return

    await websocket.accept()
    channel = f"telemetry.broadcast.{drone_id}"
    _ws_metric_inc("telemetry")

    pump_task = asyncio.create_task(
        _pump_pubsub(websocket, websocket.app.state, channel),
        name=f"ws-pubsub-{drone_id}",
    )
    hb_task = asyncio.create_task(_heartbeat(websocket), name=f"ws-hb-{drone_id}")

    try:
        # Await client disconnect (or an incoming close frame).
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                # We don't expect client→server data in v0.1, but receiving
                # keeps the socket alive and surfaces disconnects promptly.
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        _ws_metric_dec("telemetry")
        for task in (pump_task, hb_task):
            task.cancel()
        for task in (pump_task, hb_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except RuntimeError:
                pass


# ============================================================
# Vision streaming WS — R21 Step D
# ============================================================


@router.websocket("/ws/vision/{drone_id}")
async def vision_ws(
    websocket: WebSocket,
    drone_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Stream vision detection frames for a single drone.

    Subscribes to Redis pub/sub channel ``vision.frame.<drone_id>``. Every
    inference performed via ``POST /api/v1/vision/infer`` with a matching
    drone_id is fanned out here.

    Auth: same JWT scheme as telemetry (optional token param).
    """
    if token is not None:
        try:
            decode_token(token)
        except JWTError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="invalid token"
            )
            return

    await websocket.accept()
    channel = f"vision.frame.{drone_id}"
    _ws_metric_inc("vision")

    pump_task = asyncio.create_task(
        _pump_pubsub(websocket, websocket.app.state, channel),
        name=f"ws-vision-{drone_id}",
    )
    hb_task = asyncio.create_task(_heartbeat(websocket), name=f"ws-vision-hb-{drone_id}")

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        _ws_metric_dec("vision")
        for task in (pump_task, hb_task):
            task.cancel()
        for task in (pump_task, hb_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except RuntimeError:
                pass


@router.websocket("/ws/vision")
async def vision_ws_global(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Fleet-wide vision stream — subscribes to ``vision.frame.all``.

    Useful for the ops-center video wall or ML QA dashboards that want to
    see detections from every drone at once.
    """
    if token is not None:
        try:
            decode_token(token)
        except JWTError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="invalid token"
            )
            return

    await websocket.accept()
    channel = "vision.frame.all"
    _ws_metric_inc("vision-all")

    pump_task = asyncio.create_task(
        _pump_pubsub(websocket, websocket.app.state, channel),
        name="ws-vision-all",
    )
    hb_task = asyncio.create_task(_heartbeat(websocket), name="ws-vision-all-hb")

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        _ws_metric_dec("vision-all")
        for task in (pump_task, hb_task):
            task.cancel()
        for task in (pump_task, hb_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except RuntimeError:
                pass
