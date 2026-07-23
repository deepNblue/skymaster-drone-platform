"""Video stream ingestion registry — R21 Step H.

Manages RTSP/RTMP/HLS live-video sources for drones. Deliberately a
**registry + orchestration layer**, not an in-process transcoder — the
heavy pixels flow through an external SRS / MediaMTX / go2rtc gateway
that the platform simply *points at*.

Why registry-only
-----------------

* The FastAPI process must never block on ffmpeg — one stuck decoder
  would freeze all API requests.
* Every reasonable production setup already has a dedicated media
  gateway; owning yet-another transcoder inside the app server is a
  bad idea. We expose the URL pair (source_url + play_url) so the
  frontend can consume via WebRTC / HLS.

Data model
----------

* ``VideoStream``:
    - ``drone_id`` FK (nullable — some streams are ground-side cameras)
    - ``source_url``   RTSP/RTMP the drone publishes to
    - ``play_url``     HLS/WebRTC URL for the frontend to consume
    - ``protocol``     ``rtsp`` | ``rtmp`` | ``hls`` | ``webrtc``
    - ``status``       ``idle`` | ``active`` | ``stopped`` | ``error``
    - ``last_seen_at`` heartbeat timestamp
    - ``bitrate_kbps``, ``resolution``, ``fps`` — reported metadata

* ``VideoStreamProbe``: append-only health-check log so we can see when
  a stream flapped.

Endpoints (``/api/v1/video-streams``):

* ``POST   /``               register a stream (admin/operator)
* ``GET    /``               list, optional ``?drone_id=`` / ``?status=``
* ``GET    /{id}``           detail
* ``PATCH  /{id}``           update metadata
* ``POST   /{id}/heartbeat`` publisher pings (updates ``last_seen_at``)
* ``POST   /{id}/probe``     admin runs an ffprobe-style check
* ``POST   /{id}/stop``      mark ``stopped``
* ``DELETE /{id}``           remove entry

Probe implementation
--------------------

Probing is best-effort: if ``ffprobe`` is available on ``PATH``, we run
it with a 5s timeout and record ``codec_name`` / ``width`` / ``height``
/ ``r_frame_rate``. If it's missing we mark ``probe_status="skipped"``.

None of this blocks the API — probing runs in the default executor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

log = logging.getLogger(__name__)


PROTOCOLS = ("rtsp", "rtmp", "hls", "webrtc")
STATUSES = ("idle", "active", "stopped", "error")


def normalize_protocol(url: str) -> str:
    """Guess the protocol from a URL scheme; fall back to 'rtsp'."""
    if not url:
        return "rtsp"
    u = url.lower().strip()
    for p in PROTOCOLS:
        if u.startswith(p + "://"):
            return p
    if u.startswith("http"):
        # HLS lives over HTTP.
        return "hls"
    return "rtsp"


async def run_ffprobe(url: str, timeout_s: float = 5.0) -> dict:
    """Run ffprobe against ``url`` and return a compact dict.

    Never raises; returns ``{"status": "skipped"|"ok"|"error", ...}``.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"status": "skipped", "reason": "ffprobe not on PATH"}
    args = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,bit_rate",
        "-of", "json",
        "-rw_timeout", str(int(timeout_s * 1_000_000)),
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s + 2)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # pragma: no cover
                pass
            return {"status": "error", "reason": "timeout"}
        if proc.returncode != 0:
            return {
                "status": "error",
                "reason": (err or b"").decode(errors="replace")[:200] or "nonzero exit",
            }
        try:
            payload = json.loads(out.decode(errors="replace") or "{}")
        except Exception:
            return {"status": "error", "reason": "malformed ffprobe json"}
        streams = payload.get("streams") or []
        if not streams:
            return {"status": "error", "reason": "no video stream"}
        s = streams[0]
        fps = _parse_fps(s.get("r_frame_rate"))
        return {
            "status": "ok",
            "codec": s.get("codec_name"),
            "width": s.get("width"),
            "height": s.get("height"),
            "fps": fps,
            "bit_rate": _as_int(s.get("bit_rate")),
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:200]}


def _parse_fps(rate: Any) -> Optional[float]:
    if not rate or not isinstance(rate, str):
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n = float(num); d = float(den)
            return round(n / d, 2) if d else None
        except Exception:
            return None
    try:
        return float(rate)
    except Exception:
        return None


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def is_stale(last_seen_at: datetime | None, *, threshold_s: int = 30) -> bool:
    """Return True if the last heartbeat is older than the threshold."""
    if last_seen_at is None:
        return True
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_seen_at) > timedelta(seconds=threshold_s)
