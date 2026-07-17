"""MAVLink connector — receives telemetry via UDP and publishes to Redis Streams.

SkyMaster v0.1 W3-W6 implementation per SDD §5:
- Connects to a MAVLink endpoint (default ``udpin:0.0.0.0:14550``).
- Aggregates per-drone (system_id) telemetry from HEARTBEAT, GLOBAL_POSITION_INT,
  VFR_HUD, SYS_STATUS, ATTITUDE, and GPS_RAW_INT messages.
- Publishes a compact telemetry dict to Redis Stream ``telemetry:{drone_id}``
  every ``telemetry_publish_ms`` milliseconds.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from typing import Any, Dict, Optional

try:  # pymavlink is a runtime dep; keep import soft so tests can patch mavutil.
    from pymavlink import mavutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — exercised only when dep is missing
    class _MavutilStub:
        def mavlink_connection(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("pymavlink is not installed in this environment")

    mavutil = _MavutilStub()  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# --- Scaling constants (MAVLink common message set) --------------------------
# GLOBAL_POSITION_INT: lat/lon in 1e7 deg, alt/relative_alt in mm, hdg in cdeg.
_LATLON_SCALE = 1e7
_MM_TO_M = 1e-3
_CDEG_TO_DEG = 1e-2
# ATTITUDE: roll/pitch/yaw in radians.
# VFR_HUD: airspeed/groundspeed m/s, heading deg, throttle %, alt m, climb m/s.


class MavlinkConnector:
    """Subscribes to a MAVLink stream and republishes telemetry to Redis.

    Parameters
    ----------
    endpoint:
        pymavlink connection string, e.g. ``udpin:0.0.0.0:14550``.
    redis_client:
        An async Redis client (``redis.asyncio.Redis``). Optional — if ``None``
        the connector still parses messages but skips publishing (useful for
        tests).
    publish_interval_ms:
        Rolling publish cadence in milliseconds.
    """

    def __init__(
        self,
        endpoint: str = "udpin:0.0.0.0:14550",
        redis_client: Any = None,
        publish_interval_ms: int = 500,
    ) -> None:
        self.endpoint = endpoint
        self.redis = redis_client
        self.publish_interval = publish_interval_ms / 1000.0
        # drone_id (system_id) -> rolling telemetry dict
        self.telemetry: Dict[int, Dict[str, Any]] = {}
        self._conn: Any = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ conn
    def connect(self) -> Any:
        """Open the MAVLink connection (blocking; wraps mavutil)."""
        logger.info("Connecting to MAVLink endpoint %s", self.endpoint)
        # ``input=True`` for udpin means we're listening; but we also want to
        # be able to send commands back to any drone that has said hello. The
        # remote address is captured per-message by pymavlink on recv, so a
        # single udpin socket can dispatch to any peer.
        self._conn = mavutil.mavlink_connection(self.endpoint)
        return self._conn

    # ---------------------------------------------------------------- command
    def send_command(
        self,
        target_system: int,
        command: int,
        params: tuple[float, ...] = (),
    ) -> bool:
        """Send a MAVLink COMMAND_LONG to a drone (best-effort)."""
        if self._conn is None:
            logger.warning("send_command: connection not open")
            return False
        try:
            # Pad to 7 params.
            padded = list(params) + [0.0] * (7 - len(params))
            self._conn.mav.command_long_send(
                target_system,
                0,                     # target_component (0 = broadcast)
                int(command),
                0,                     # confirmation
                *padded[:7],
            )
            logger.info(
                "COMMAND_LONG → sysid=%s cmd=%s params=%s",
                target_system, command, padded[:7],
            )
            return True
        except Exception:
            logger.exception("send_command failed")
            return False

    def send_mission_items(
        self,
        target_system: int,
        waypoints: list[dict],
    ) -> bool:
        """Upload a waypoint list to the drone via classic MISSION protocol.

        Each waypoint dict may have keys: ``lat``, ``lng``, ``alt``,
        ``hold`` (seconds), ``command`` (default NAV_WAYPOINT=16).

        This is a *shortened* implementation of the MAVLink mission upload
        handshake — it sends MISSION_COUNT then MISSION_ITEM_INT records
        without waiting for MISSION_REQUEST_INT acks. For a real vehicle
        we'd bind ack callbacks; for FakeDrone this is enough to exercise
        the round-trip and verify the connector can transmit.
        """
        if self._conn is None:
            logger.warning("send_mission_items: connection not open")
            return False
        try:
            self._conn.mav.mission_count_send(
                target_system, 0, len(waypoints), 0
            )
            for idx, wp in enumerate(waypoints):
                self._conn.mav.mission_item_int_send(
                    target_system,
                    0,                                        # target_component
                    idx,
                    3,                                        # MAV_FRAME_GLOBAL_RELATIVE_ALT
                    int(wp.get("command", 16)),               # MAV_CMD_NAV_WAYPOINT
                    1 if idx == 0 else 0,                     # current
                    1,                                        # autocontinue
                    float(wp.get("hold", 0.0)),               # param1
                    0.0, 0.0, 0.0,                            # param2..4
                    int(float(wp["lat"]) * _LATLON_SCALE),
                    int(float(wp["lng"]) * _LATLON_SCALE),
                    float(wp.get("alt", 50.0)),
                    0,                                        # mission_type
                )
            logger.info(
                "MISSION uploaded → sysid=%s items=%d", target_system, len(waypoints)
            )
            return True
        except Exception:
            logger.exception("send_mission_items failed")
            return False

    # ------------------------------------------------------------- parsing
    def _slot(self, sysid: int) -> Dict[str, Any]:
        return self.telemetry.setdefault(
            sysid,
            {
                "drone_id": sysid,
                "lat": None,
                "lng": None,
                "alt": None,
                "speed": None,
                "heading": None,
                "roll": None,
                "pitch": None,
                "yaw": None,
                "battery_pct": None,
                "voltage_battery": None,
                "gps_sats": None,
                "throttle": None,
                "climb": None,
                "airspeed": None,
                "mode": None,
                "base_mode": None,
                "ts": None,
            },
        )

    def handle_message(self, msg: Any) -> Optional[Dict[str, Any]]:
        """Update rolling telemetry from a single MAVLink message.

        Returns the slot that was updated (or ``None`` if the message type is
        not tracked).
        """
        if msg is None:
            return None
        mtype = msg.get_type()
        sysid = getattr(msg, "_header", None)
        sysid = msg.get_srcSystem() if hasattr(msg, "get_srcSystem") else 1
        slot = self._slot(sysid)

        if mtype == "HEARTBEAT":
            slot["mode"] = getattr(msg, "custom_mode", None)
            slot["base_mode"] = getattr(msg, "base_mode", None)
            logger.debug(
                "HEARTBEAT sysid=%s base_mode=%s custom_mode=%s",
                sysid, slot["base_mode"], slot["mode"],
            )
        elif mtype == "GLOBAL_POSITION_INT":
            slot["lat"] = msg.lat / _LATLON_SCALE
            slot["lng"] = msg.lon / _LATLON_SCALE
            slot["alt"] = msg.alt * _MM_TO_M
            slot["heading"] = (
                msg.hdg * _CDEG_TO_DEG if msg.hdg != 65535 else slot["heading"]
            )
        elif mtype == "VFR_HUD":
            slot["airspeed"] = msg.airspeed
            slot["speed"] = msg.groundspeed
            slot["heading"] = msg.heading
            slot["throttle"] = msg.throttle
            # Prefer GPS altitude when present; else VFR_HUD alt as fallback.
            if slot["alt"] is None:
                slot["alt"] = msg.alt
            slot["climb"] = msg.climb
        elif mtype == "SYS_STATUS":
            pct = msg.battery_remaining
            slot["battery_pct"] = pct if pct != -1 else None
            slot["voltage_battery"] = (
                msg.voltage_battery * 1e-3
                if msg.voltage_battery != 65535
                else None
            )
        elif mtype == "ATTITUDE":
            slot["roll"] = msg.roll
            slot["pitch"] = msg.pitch
            slot["yaw"] = msg.yaw
        elif mtype == "GPS_RAW_INT":
            slot["gps_sats"] = (
                msg.satellites_visible
                if msg.satellites_visible != 255
                else None
            )
        else:
            return None

        slot["ts"] = time.time()
        logger.debug("Updated slot for sysid=%s from %s", sysid, mtype)
        return slot

    # -------------------------------------------------------------- publish
    def _stream_payload(self, slot: Dict[str, Any]) -> Dict[str, str]:
        """Coerce the slot to a Redis-stream-safe (str-only) mapping."""
        fields = ("ts", "lat", "lng", "alt", "speed", "heading",
                  "roll", "pitch", "yaw", "battery_pct", "gps_sats")
        return {k: ("" if slot.get(k) is None else str(slot[k])) for k in fields}

    async def publish_once(self) -> None:
        """Publish the current rolling telemetry for every known drone."""
        if self.redis is None:
            return
        import json as _json
        for drone_id, slot in list(self.telemetry.items()):
            stream = f"telemetry:{drone_id}"
            channel = f"telemetry.broadcast.{drone_id}"
            payload = self._stream_payload(slot)
            try:
                await self.redis.xadd(stream, payload, maxlen=1000, approximate=True)
            except Exception:  # noqa: BLE001 — keep loop alive
                logger.exception("Failed to XADD to %s", stream)
            try:
                await self.redis.publish(channel, _json.dumps(payload))
            except Exception:  # noqa: BLE001
                logger.exception("Failed to PUBLISH to %s", channel)

    # -------------------------------------------------------------- loops
    async def read_loop(self) -> None:
        """Pump MAVLink messages from the (blocking) socket into the parser."""
        loop = asyncio.get_running_loop()
        assert self._conn is not None, "connect() must be called first"
        while not self._stop.is_set():
            msg = await loop.run_in_executor(
                None,
                lambda: self._conn.recv_match(blocking=True, timeout=1.0),
            )
            if msg is None:
                continue
            try:
                self.handle_message(msg)
            except Exception:  # noqa: BLE001
                logger.exception("Error parsing MAVLink message")

    async def publish_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.publish_once()
            except Exception:  # noqa: BLE001
                logger.exception("publish_loop iteration failed")
            await asyncio.sleep(self.publish_interval)

    async def run(self) -> None:
        """Run until :meth:`stop` is called (SIGINT/SIGTERM friendly).

        Reconnects on unexpected failures with exponential backoff.
        """
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.connect()
                backoff = 1.0
                await asyncio.gather(self.read_loop(), self.publish_loop())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "MAVLink loop crashed; reconnecting in %.1fs", backoff
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    def stop(self) -> None:
        logger.info("Stopping MAVLink connector")
        self._stop.set()


# ------------------------------------------------------------------ main
def _build_redis_client() -> Any:
    """Return a redis client honoring ``USE_FAKE_REDIS`` (dev-stack switch)."""
    from app.services.fake_redis_singleton import get_redis, is_fake_enabled

    if is_fake_enabled():
        return get_redis()
    import redis.asyncio as aioredis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.from_url(redis_url, decode_responses=True)


async def _amain() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    endpoint = os.getenv("MAVLINK_ENDPOINT", "udpin:0.0.0.0:14550")
    publish_ms = int(os.getenv("TELEMETRY_PUBLISH_MS", "500"))

    redis_client = _build_redis_client()
    connector = MavlinkConnector(
        endpoint=endpoint,
        redis_client=redis_client,
        publish_interval_ms=publish_ms,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, connector.stop)
        except NotImplementedError:  # Windows
            pass

    try:
        await connector.run()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_amain())
