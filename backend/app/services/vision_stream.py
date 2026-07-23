"""Vision stream broadcaster — R21 Step D.

Fan-out vision detections over WebSocket via Redis pub/sub.

Architecture (SDD §5.2 pattern, re-used from telemetry):

    POST /api/v1/vision/infer
             │
             ▼
    publish_vision_frame(...)  ──►  Redis PUB  vision.frame.<drone_id>
                                     │             │
                                     │             ▼   (any drone)
                                     ▼             ▼
                            ws://.../ws/vision/{drone_id}       ws://.../ws/vision
                                     │
                                     ▼
                          browser (overlay bbox)

Design principles
-----------------

1. **Non-blocking.** Vision inference must never wait on Redis. If Redis is
   down or slow, we drop the message and log DEBUG — the persisted
   detection is still in the DB.
2. **Small payloads.** We omit the input image; only bbox + label + meta
   travels over the WS. Browsers overlay onto the local video feed.
3. **Two channels** — per-drone and global:
     * ``vision.frame.<drone_id>``  → focused fleet dashboards
     * ``vision.frame.all``          → global ops-center wall
   Callers publish to whichever channels apply.

The WebSocket handler is defined in ``app/api/v1/websocket.py`` — this
module owns *only* the publisher side plus the deterministic channel
resolvers so both sides never drift.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Redis channel prefixes — kept in sync with the WS handler.
VISION_CHANNEL_ALL = "vision.frame.all"


def channel_for_drone(drone_id: str | None) -> str | None:
    """Return the pub/sub channel for a specific drone (or None if no id)."""
    if not drone_id:
        return None
    return f"vision.frame.{drone_id}"


def _serialise_detection(d: Any) -> dict:
    """Marshal DetectionBox → JSON-safe dict. Accepts either a DetectionBox or
    an already-dict result (defensive)."""
    if isinstance(d, dict):
        return d
    return {
        "label": d.label,
        "confidence": d.confidence,
        "bbox": d.bbox,
        "track_id": d.track_id,
        "attrs": d.attrs,
    }


def build_frame_payload(
    *,
    result: Any,            # DetectionFrame
    drone_id: str | None,
    mission_id: str | None,
    stream_key: str | None,
    lat: float | None,
    lng: float | None,
    alt_m: float | None,
    persisted_ids: list[str] | None,
) -> dict:
    """Assemble the WS-bound JSON envelope for a vision frame."""
    return {
        "type": "vision.frame",
        "runtime": result.runtime,
        "model_tag": result.model_tag,
        "latency_ms": result.latency_ms,
        "frame_idx": result.frame_idx,
        "drone_id": drone_id,
        "mission_id": mission_id,
        "stream_key": stream_key,
        "lat": lat,
        "lng": lng,
        "alt_m": alt_m,
        "detections": [_serialise_detection(d) for d in result.detections],
        "persisted_ids": persisted_ids or [],
        "count": len(result.detections),
    }


async def publish_vision_frame(
    redis: Any,
    payload: dict,
    *,
    drone_id: str | None,
) -> int:
    """Publish the frame to per-drone AND global channels.

    Returns the total number of subscribers reached (best-effort).
    Never raises — any Redis error is swallowed with DEBUG log.
    """
    if redis is None:
        return 0
    body = json.dumps(payload, separators=(",", ":"))
    total = 0
    channels = [VISION_CHANNEL_ALL]
    ch = channel_for_drone(drone_id)
    if ch:
        channels.append(ch)
    for c in channels:
        try:
            n = await redis.publish(c, body)
            if isinstance(n, int):
                total += n
        except Exception as exc:  # pragma: no cover
            log.debug("vision publish to %s failed: %s", c, exc)
    return total
