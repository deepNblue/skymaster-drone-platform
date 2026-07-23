"""Telemetry consumer — reads Redis Streams, batch-inserts to Postgres,
and fans out to a pub/sub channel for WebSocket subscribers.

SkyMaster v0.1 W3-W6 (SDD §5.2/§5.3):

Pipeline
--------
    mavlink_connector  ->  redis stream: telemetry:{drone_id}
                                |
                                v
                        TelemetryConsumer
                        ├──> flight_logs (batch INSERT)
                        └──> redis pub/sub: telemetry.broadcast.{drone_id}
                                            (WS server subscribes)

Configuration
-------------
- ``TELEMETRY_BATCH_SIZE``  (default 100)
- ``TELEMETRY_FLUSH_MS``    (default 5000)
- ``TELEMETRY_STREAM_PREFIX`` (default ``telemetry:``)
- ``TELEMETRY_STREAM_SCAN_INTERVAL_S`` (default 10)
- ``REDIS_URL``, ``DATABASE_URL`` (inherit from :mod:`app.config`)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from app.db import AsyncSessionLocal
from app.models.flight_log import FlightLog

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- helpers
def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_uuid(value: Any) -> Optional[UUID]:
    """Coerce a stream key suffix into a UUID; return None if not a UUID.

    In v0.1 the mavlink connector uses integer system_ids for the stream
    suffix (e.g. ``telemetry:1``). Once the fleet registration flow is in
    place these become drone UUIDs. Both shapes are accepted here — non-UUID
    values are surfaced as ``None`` so the caller can decide what to do.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ consumer
class TelemetryConsumer:
    """Consumes telemetry:{drone_id} streams, batches to DB, fans out via pub/sub.

    Parameters
    ----------
    redis_client:
        An async Redis client (``redis.asyncio.Redis``).
    session_factory:
        Async SQLAlchemy sessionmaker (defaults to :data:`AsyncSessionLocal`).
    batch_size:
        Flush the buffer when it reaches this many records.
    flush_ms:
        Flush the buffer at least this often (milliseconds), even if not full.
    stream_prefix:
        Redis SCAN pattern prefix; matches ``{prefix}*`` streams.
    scan_interval_s:
        How often to rescan Redis for new drone streams.
    read_block_ms:
        XREAD block timeout — controls how promptly the loop wakes for flushes.
    """

    def __init__(
        self,
        redis_client: Any,
        session_factory: Any = None,
        batch_size: int = 100,
        flush_ms: int = 5000,
        stream_prefix: str = "telemetry:",
        scan_interval_s: float = 10.0,
        read_block_ms: int = 500,
    ) -> None:
        self.redis = redis_client
        self._session_factory = session_factory or AsyncSessionLocal
        self.batch_size = batch_size
        self.flush_interval = flush_ms / 1000.0
        self.stream_prefix = stream_prefix
        self.scan_interval_s = scan_interval_s
        self.read_block_ms = read_block_ms

        # Per-stream last-seen id for XREAD cursor. "$" = only new messages.
        self._cursors: Dict[str, str] = {}
        self._buffer: List[Dict[str, Any]] = []
        self._last_flush_at: float = time.monotonic()
        self._last_scan_at: float = 0.0
        self._stop = asyncio.Event()

    # ------------------------------------------------------------- discovery
    async def discover_streams(self) -> List[str]:
        """SCAN Redis for stream keys matching ``{stream_prefix}*``."""
        pattern = f"{self.stream_prefix}*"
        found: List[str] = []
        try:
            async for key in self.redis.scan_iter(match=pattern, count=100):
                found.append(key if isinstance(key, str) else key.decode())
        except Exception:  # noqa: BLE001
            logger.exception("Redis SCAN failed for pattern %s", pattern)
            return list(self._cursors.keys())

        for key in found:
            self._cursors.setdefault(key, "$")
        # Drop cursors for streams that no longer exist (kept minimal — GC).
        stale = set(self._cursors) - set(found)
        for key in stale:
            self._cursors.pop(key, None)
        return list(self._cursors.keys())

    # ---------------------------------------------------------- decode entry
    def _drone_id_from_stream(self, stream: str) -> Optional[str]:
        if not stream.startswith(self.stream_prefix):
            return None
        return stream[len(self.stream_prefix):] or None

    def _decode_entry(
        self, stream: str, entry_id: str, fields: Mapping[Any, Any]
    ) -> Optional[Dict[str, Any]]:
        """Convert a raw XREAD entry into a normalized telemetry dict."""
        # Redis may hand us bytes if decode_responses=False.
        def _s(v: Any) -> Any:
            return v.decode() if isinstance(v, (bytes, bytearray)) else v

        data: Dict[str, Any] = {_s(k): _s(v) for k, v in fields.items()}
        drone_id_raw = self._drone_id_from_stream(stream)
        if drone_id_raw is None:
            return None

        data["drone_id"] = drone_id_raw
        data["entry_id"] = entry_id
        data["stream"] = stream
        # Ensure ts is a float; fall back to now.
        ts = _to_float(data.get("ts"))
        data["ts"] = ts if ts is not None else time.time()
        return data

    # --------------------------------------------------------- DB conversion
    @staticmethod
    def _to_flight_log_row(entry: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a flight_logs INSERT row from a normalized entry.

        Returns ``None`` if the drone_id can't be coerced to a UUID (the DB
        column is UUID-typed).
        """
        drone_uuid = _to_uuid(entry.get("drone_id"))
        if drone_uuid is None:
            return None

        from datetime import datetime, timezone
        ts_float = _to_float(entry.get("ts")) or time.time()
        return {
            "time": datetime.fromtimestamp(ts_float, tz=timezone.utc),
            "drone_id": drone_uuid,
            "mission_id": _to_uuid(entry.get("mission_id")),
            "lat": _to_float(entry.get("lat")),
            "lng": _to_float(entry.get("lng")),
            "alt": _to_float(entry.get("alt")),
            "speed": _to_float(entry.get("speed")),
            "heading": _to_float(entry.get("heading")),
            "roll": _to_float(entry.get("roll")),
            "pitch": _to_float(entry.get("pitch")),
            "yaw": _to_float(entry.get("yaw")),
            "battery_pct": _to_float(entry.get("battery_pct")),
            "rssi": _to_int(entry.get("rssi")),
            "gps_sats": _to_int(entry.get("gps_sats")),
            "flight_mode": entry.get("flight_mode") or entry.get("mode"),
        }

    # ------------------------------------------------------------- broadcast
    async def broadcast(self, entry: Mapping[str, Any]) -> None:
        """Publish a single entry to the drone-specific fan-out channel.

        Also opportunistically forwards the position to the Remote ID
        broadcast service (ASTM F3411-22a Network RID mode) so third
        parties / CAA regulators can pull `/api/v1/remoteid/messages`
        without touching internal fleet data.
        """
        drone_id = entry.get("drone_id")
        if drone_id is None:
            return
        channel = f"telemetry.broadcast.{drone_id}"
        payload = {k: v for k, v in entry.items() if k not in ("entry_id", "stream")}
        try:
            await self.redis.publish(channel, json.dumps(payload, default=str))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to publish broadcast to %s", channel)

        # Remote ID broadcast — best effort, never blocks telemetry.
        try:
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is None or lng is None:
                return
            from app.services.remoteid import RemoteIDMessage, publish as _rid_publish
            alt = entry.get("alt") or 0.0
            speed = entry.get("speed") or 0.0
            heading = entry.get("heading") or 0.0
            mode = (entry.get("flight_mode") or entry.get("mode") or "").upper()
            status = "airborne" if mode not in ("LANDED", "DISARMED", "STANDBY") else "ground"
            msg = RemoteIDMessage(
                uas_id=str(drone_id),
                uas_id_type=3,   # UTM UUID
                lat=float(lat),
                lng=float(lng),
                alt_m=float(alt),
                track_deg=float(heading),
                speed_ms=float(speed),
                operator_id=str(entry.get("operator_id") or entry.get("org_id") or ""),
                status=status,
            )
            _rid_publish(msg)
        except Exception:  # noqa: BLE001
            logger.debug("Remote ID publish skipped", exc_info=True)

    # -------------------------------------------------------------- DB flush
    async def flush(self) -> int:
        """Persist the buffered entries to flight_logs. Returns rows inserted.

        On DB error the buffer is preserved and an exponential backoff is
        applied by the caller loop (see :meth:`run`).
        """
        if not self._buffer:
            self._last_flush_at = time.monotonic()
            return 0

        rows: List[Dict[str, Any]] = []
        dropped_non_uuid = 0
        for entry in self._buffer:
            row = self._to_flight_log_row(entry)
            if row is None:
                dropped_non_uuid += 1
                continue
            rows.append(row)

        count = len(rows)
        if dropped_non_uuid:
            logger.warning(
                "Skipped %d telemetry entries with non-UUID drone_id "
                "(v0.1 mavlink still uses system_id ints)",
                dropped_non_uuid,
            )

        if count == 0:
            self._buffer.clear()
            self._last_flush_at = time.monotonic()
            return 0

        try:
            async with self._session_factory() as session:
                await session.execute(insert(FlightLog), rows)
                await session.commit()
        except SQLAlchemyError:
            logger.exception(
                "flight_logs batch insert failed (buffered=%d) — will retry",
                count,
            )
            # Preserve buffer for retry; caller applies backoff.
            raise

        logger.info("Flushed %d telemetry rows to flight_logs", count)
        self._buffer.clear()
        self._last_flush_at = time.monotonic()
        return count

    # ------------------------------------------------------------ read cycle
    def _build_read_arg(self) -> Optional[Dict[str, str]]:
        if not self._cursors:
            return None
        return dict(self._cursors)

    async def _xread(
        self, streams: Mapping[str, str]
    ) -> List[Tuple[str, List[Tuple[str, Mapping[Any, Any]]]]]:
        """Wrap XREAD, normalizing the return shape (str-keyed)."""
        raw = await self.redis.xread(streams=dict(streams), block=self.read_block_ms, count=self.batch_size)
        if not raw:
            return []
        normalized: List[Tuple[str, List[Tuple[str, Mapping[Any, Any]]]]] = []
        for stream, entries in raw:
            s = stream.decode() if isinstance(stream, (bytes, bytearray)) else stream
            norm_entries = [
                (
                    eid.decode() if isinstance(eid, (bytes, bytearray)) else eid,
                    fields,
                )
                for eid, fields in entries
            ]
            normalized.append((s, norm_entries))
        return normalized

    async def _tick(self) -> None:
        """One iteration: rescan (if due), XREAD, buffer, broadcast, maybe flush."""
        now = time.monotonic()
        if now - self._last_scan_at >= self.scan_interval_s:
            await self.discover_streams()
            self._last_scan_at = now

        streams = self._build_read_arg()
        if streams:
            try:
                results = await self._xread(streams)
            except Exception:  # noqa: BLE001
                logger.exception("XREAD failed; will retry")
                results = []

            for stream, entries in results:
                for entry_id, fields in entries:
                    entry = self._decode_entry(stream, entry_id, fields)
                    if entry is None:
                        continue
                    self._cursors[stream] = entry_id
                    self._buffer.append(entry)
                    await self.broadcast(entry)
        else:
            # No streams yet — sleep a bit so we don't spin.
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

        # Flush triggers: size or timeout.
        size_trigger = len(self._buffer) >= self.batch_size
        time_trigger = (time.monotonic() - self._last_flush_at) * 1000.0 >= (
            self.flush_interval * 1000.0
        )
        if size_trigger or (time_trigger and self._buffer):
            await self.flush()

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        """Main loop. Runs until :meth:`stop` is called.

        Reconnects/retries with exponential backoff on unexpected errors.
        """
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._tick()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "TelemetryConsumer tick failed; backing off %.1fs", backoff
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

        # Best-effort final flush on shutdown.
        if self._buffer:
            try:
                await self.flush()
            except Exception:  # noqa: BLE001
                logger.exception("Final flush on shutdown failed")

    def stop(self) -> None:
        logger.info("Stopping telemetry consumer")
        self._stop.set()


# --------------------------------------------------------------------- main
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

    batch_size = int(os.getenv("TELEMETRY_BATCH_SIZE", "100"))
    flush_ms = int(os.getenv("TELEMETRY_FLUSH_MS", "5000"))
    stream_prefix = os.getenv("TELEMETRY_STREAM_PREFIX", "telemetry:")
    scan_interval_s = float(os.getenv("TELEMETRY_STREAM_SCAN_INTERVAL_S", "10"))

    redis_client = _build_redis_client()
    consumer = TelemetryConsumer(
        redis_client=redis_client,
        batch_size=batch_size,
        flush_ms=flush_ms,
        stream_prefix=stream_prefix,
        scan_interval_s=scan_interval_s,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, consumer.stop)
        except NotImplementedError:  # Windows
            pass

    try:
        await consumer.run()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_amain())
