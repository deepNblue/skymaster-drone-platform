"""Remote ID broadcast mock — v2.0 civil aviation compliance.

Implements the ASTM F3411-22a / EASA EAB-2023 Remote ID standard as a
mock adapter. In production this would drive a real Bluetooth/WiFi
beacon or push to the national Remote ID network. Here we expose an
HTTP endpoint that any listener (民航局稽查、地方公安、AAM) can pull
current in-flight aircraft from, per the "Network Remote ID" mode.

Message fields (per ASTM F3411-22a §5.4 Basic ID + Location):
  - uas_id_type: 1=Serial 2=CAA 3=UTM(UUID) 4=Session ID
  - uas_id: registration or session token
  - lat, lng, alt_m (WGS84)
  - track_deg (0-359, true north)
  - speed_ms
  - vertical_rate_ms
  - height_agl_m
  - timestamp (unix seconds)
  - operator_id (org token / pilot license)
  - status: airborne | ground

Broadcast frequency ≥ 1 Hz for compliant systems.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from typing import Optional

_STATE: dict[str, "RemoteIDMessage"] = {}


@dataclass
class RemoteIDMessage:
    uas_id: str                     # aircraft registration / session token
    uas_id_type: int = 1            # 1 = Serial (ANSI/CTA-2063-A)
    lat: float = 0.0
    lng: float = 0.0
    alt_m: float = 0.0              # WGS84 ellipsoidal
    track_deg: float = 0.0          # 0..359 true north
    speed_ms: float = 0.0
    vertical_rate_ms: float = 0.0
    height_agl_m: float = 0.0
    timestamp: float = field(default_factory=lambda: time.time())
    operator_id: str = ""
    status: str = "ground"          # "airborne" | "ground"
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None


def publish(msg: RemoteIDMessage) -> None:
    """Publish a Remote ID position update for one aircraft."""
    msg.timestamp = time.time()
    _STATE[msg.uas_id] = msg


def get_all() -> list[dict]:
    """Return the current airborne fleet snapshot (post-purge)."""
    now = time.time()
    # Age-out records older than 30s per ASTM rec.
    stale = [k for k, v in _STATE.items() if now - v.timestamp > 30]
    for k in stale:
        _STATE.pop(k, None)
    return [asdict(v) for v in _STATE.values()]


def get_one(uas_id: str) -> Optional[dict]:
    msg = _STATE.get(uas_id)
    return asdict(msg) if msg else None


def clear() -> None:
    """Test hook."""
    _STATE.clear()
