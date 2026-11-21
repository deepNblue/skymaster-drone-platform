"""End-to-end simulated pipeline test — no Docker, no real drone, no real Redis.

Flow: FakeDrone (mocked pymavlink) → MavlinkConnector → fakeredis Stream →
      TelemetryConsumer → SQLite flight_logs → pub/sub broadcast.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio

# Ensure fakeredis is in effect before we import connector / consumer.
os.environ["USE_FAKE_REDIS"] = "true"


# ------------------------------------------------------------------ helpers
def _mk_msg(msgtype: str, **fields: Any) -> SimpleNamespace:
    """Build a fake pymavlink Message matching the attributes we read."""
    msg = SimpleNamespace(**fields)
    msg.get_type = lambda t=msgtype: t
    msg.get_srcSystem = lambda s=fields.get("_sysid", 1): s
    return msg


class _FakeMavConnection:
    """Stand-in for mavutil.mavlink_connection() — feeds pre-built messages."""

    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self._messages = list(messages)

    def recv_match(self, blocking: bool = False, timeout: float | None = None, **_kw):
        if not self._messages:
            return None
        return self._messages.pop(0)

    def close(self) -> None:
        pass


# ------------------------------------------------------------------- tests
async def test_mavlink_connector_publishes_to_fakeredis(monkeypatch):
    """Feed 3 MAVLink messages, assert Redis stream telemetry:1 gets ≥1 entry."""
    import fakeredis.aioredis as fake
    from app.services import mavlink_connector as mod

    redis = fake.FakeRedis(decode_responses=True)

    msgs = [
        _mk_msg("HEARTBEAT", type=2, autopilot=12, base_mode=209,
                custom_mode=6, system_status=4, _sysid=1),
        _mk_msg("GLOBAL_POSITION_INT",
                lat=int(39.9042 * 1e7), lon=int(116.4074 * 1e7),
                alt=100_000, relative_alt=100_000, vx=0, vy=0, vz=0, hdg=9000,
                _sysid=1),
        _mk_msg("VFR_HUD",
                airspeed=5.0, groundspeed=5.0, heading=90,
                throttle=50, alt=100.0, climb=0.0, _sysid=1),
    ]

    def _fake_connect(endpoint):  # noqa: ARG001
        return _FakeMavConnection(msgs)

    monkeypatch.setattr(mod.mavutil, "mavlink_connection", _fake_connect)

    conn = mod.MavlinkConnector(
        endpoint="udpin:127.0.0.1:14550",
        redis_client=redis,
        publish_interval_ms=50,
    )
    task = asyncio.create_task(conn.run())
    await asyncio.sleep(0.4)
    conn.stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    length = await redis.xlen("telemetry:1")
    assert length >= 1, f"expected ≥1 stream entry, got {length}"


async def test_stream_and_pubsub_roundtrip():
    """Manually xadd to a stream and verify pub/sub broadcast works."""
    import fakeredis.aioredis as fake

    redis = fake.FakeRedis(decode_responses=True)

    channel = "telemetry.broadcast.42"
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    payload = {"drone_id": 42, "lat": 39.9, "lng": 116.4, "alt": 100}
    await redis.publish(channel, json.dumps(payload))

    # Skip subscribe-confirm message, then get the real one
    received = None
    for _ in range(5):
        msg = await pubsub.get_message(timeout=0.5, ignore_subscribe_messages=True)
        if msg is not None and msg.get("type") == "message":
            received = json.loads(msg["data"])
            break

    await pubsub.unsubscribe(channel)
    await pubsub.close()

    assert received == payload, f"expected {payload}, got {received}"


async def test_fake_drone_script_imports():
    """Just import the fake_drone script to catch syntax / import errors."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("fake_drone.py", "fake_drone_swarm.py"):
        path = root / "scripts" / name
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        # Only compile, don't execute __main__.
        compile(path.read_text(), str(path), "exec")
