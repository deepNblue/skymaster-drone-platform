"""Unit tests for TelemetryConsumer.

We use ``unittest.mock`` for the Redis client and session factory so tests
run without any external services. Each test targets a single behaviour:

- Batch-size trigger → DB insert
- Timeout trigger → partial flush
- Every buffered entry → broadcast on the correct pub/sub channel
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# conftest.py sets DATABASE_URL / REDIS_URL / JWT_SECRET before app imports.
from app.services.telemetry_consumer import TelemetryConsumer


# -------------------------------------------------------------------- helpers
class _StubSession:
    """Async context-manager session stub — records execute() calls."""

    def __init__(self, recorder: list) -> None:
        self._recorder = recorder
        self.execute = AsyncMock(side_effect=self._record)
        self.commit = AsyncMock()

    async def _record(self, stmt, rows=None):
        self._recorder.append(rows if rows is not None else stmt)

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _stub_session_factory():
    """Return (factory, recorder). Recorder is populated on execute()."""
    recorder: list = []
    factory = MagicMock(side_effect=lambda: _StubSession(recorder))
    return factory, recorder


def _make_consumer(**overrides) -> TelemetryConsumer:
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock(return_value=1)
    factory, _ = _stub_session_factory()
    return TelemetryConsumer(
        redis_client=redis_mock,
        session_factory=factory,
        **overrides,
    )


def _entry(drone_uuid: str, ts: float = 1_700_000_000.0) -> dict:
    return {
        "drone_id": drone_uuid,
        "ts": ts,
        "lat": "1.23",
        "lng": "4.56",
        "alt": "10.0",
        "speed": "5.0",
        "heading": "90.0",
        "roll": "0.01",
        "pitch": "0.02",
        "yaw": "0.03",
        "battery_pct": "85",
        "gps_sats": "12",
    }


# ------------------------------------------------------------------- fixtures
@pytest.fixture
def drone_uuid() -> str:
    return str(uuid4())


# ------------------------------------------------------------------ tests: size
async def test_flush_triggers_after_batch_size(drone_uuid: str) -> None:
    """Filling the buffer to batch_size N triggers a single INSERT of N rows."""
    factory, recorded = _stub_session_factory()
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock(return_value=1)

    consumer = TelemetryConsumer(
        redis_client=redis_mock,
        session_factory=factory,
        batch_size=100,
        flush_ms=60_000,  # keep the timeout out of the way
    )

    consumer._buffer.extend(_entry(drone_uuid) for _ in range(100))
    inserted = await consumer.flush()

    assert inserted == 100
    assert len(recorded) == 1
    assert isinstance(recorded[0], list)
    assert len(recorded[0]) == 100
    # Buffer is emptied after a successful flush.
    assert consumer._buffer == []


# --------------------------------------------------------------- tests: timeout
async def test_flush_triggers_on_timeout_with_partial_batch(drone_uuid: str) -> None:
    """A tick after flush_ms elapses flushes whatever is buffered."""
    factory, recorded = _stub_session_factory()
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock(return_value=1)
    # No streams discovered → _xread is never called; _tick sleeps briefly.
    redis_mock.scan_iter = MagicMock(side_effect=lambda **_: _aiter([]))
    redis_mock.xread = AsyncMock(return_value=[])

    consumer = TelemetryConsumer(
        redis_client=redis_mock,
        session_factory=factory,
        batch_size=1000,      # size trigger stays disarmed
        flush_ms=50,          # very short so the test is fast
        scan_interval_s=0.01,
        read_block_ms=10,
    )

    # Prime the buffer directly and rewind the flush clock past the deadline.
    consumer._buffer.extend(_entry(drone_uuid) for _ in range(5))
    consumer._last_flush_at -= 10.0  # simulate elapsed time

    # Register at least one stream so _tick attempts XREAD instead of sleeping.
    consumer._cursors[f"telemetry:{drone_uuid}"] = "$"

    await consumer._tick()

    assert len(recorded) == 1, "timeout should trigger exactly one flush"
    assert len(recorded[0]) == 5
    assert consumer._buffer == []


# ------------------------------------------------------------- tests: broadcast
async def test_broadcast_publishes_to_drone_channel(drone_uuid: str) -> None:
    """Each buffered entry results in a publish() on telemetry.broadcast.{id}."""
    consumer = _make_consumer(batch_size=10, flush_ms=60_000)
    entry = _entry(drone_uuid)

    await consumer.broadcast(entry)

    consumer.redis.publish.assert_awaited_once()
    channel, payload = consumer.redis.publish.await_args.args
    assert channel == f"telemetry.broadcast.{drone_uuid}"
    # Payload is JSON — verify it round-trips and preserves drone_id.
    import json
    decoded = json.loads(payload)
    assert decoded["drone_id"] == drone_uuid
    assert decoded["ts"] == entry["ts"]
    # Internal-only keys must not leak downstream.
    assert "entry_id" not in decoded
    assert "stream" not in decoded


async def test_broadcast_called_for_each_streamed_entry(drone_uuid: str) -> None:
    """A tick that consumes 3 stream entries should publish 3 times."""
    factory, _ = _stub_session_factory()
    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock(return_value=1)
    redis_mock.scan_iter = MagicMock(
        side_effect=lambda **_: _aiter([f"telemetry:{drone_uuid}"])
    )
    redis_mock.xread = AsyncMock(
        return_value=[
            (
                f"telemetry:{drone_uuid}",
                [
                    ("1-0", {"ts": "1", "lat": "1", "lng": "2"}),
                    ("1-1", {"ts": "2", "lat": "1", "lng": "2"}),
                    ("1-2", {"ts": "3", "lat": "1", "lng": "2"}),
                ],
            )
        ]
    )

    consumer = TelemetryConsumer(
        redis_client=redis_mock,
        session_factory=factory,
        batch_size=1000,
        flush_ms=60_000,
        scan_interval_s=0.01,
        read_block_ms=10,
    )

    await consumer._tick()

    assert redis_mock.publish.await_count == 3
    channels = {call.args[0] for call in redis_mock.publish.await_args_list}
    assert channels == {f"telemetry.broadcast.{drone_uuid}"}
    assert len(consumer._buffer) == 3


# -------------------------------------------------------------------- helpers
async def _aiter(items):
    """Turn a list into an async iterator (matches redis.scan_iter shape)."""
    for item in items:
        yield item
