"""Tests for R21 Step D — Vision WebSocket streaming."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# vision_stream helpers — pure functions, no HTTP
# ---------------------------------------------------------------------------


def test_channel_for_drone():
    from app.services.vision_stream import channel_for_drone, VISION_CHANNEL_ALL
    assert channel_for_drone("D001") == "vision.frame.D001"
    assert channel_for_drone(None) is None
    assert channel_for_drone("") is None
    assert VISION_CHANNEL_ALL == "vision.frame.all"


def test_build_frame_payload_shape():
    from app.services.vision_runtime import DetectionBox, DetectionFrame
    from app.services.vision_stream import build_frame_payload

    frame = DetectionFrame(
        detections=[
            DetectionBox(label="person", confidence=0.9,
                         bbox=[0.1, 0.2, 0.3, 0.4], track_id=5),
        ],
        model_tag="yolov9-s", runtime="onnx", latency_ms=12.34, frame_idx=7,
    )
    p = build_frame_payload(
        result=frame, drone_id="D1", mission_id="M2", stream_key="s1",
        lat=30.0, lng=104.0, alt_m=120.0,
        persisted_ids=["a", "b"],
    )
    assert p["type"] == "vision.frame"
    assert p["drone_id"] == "D1"
    assert p["mission_id"] == "M2"
    assert p["count"] == 1
    assert p["detections"][0]["label"] == "person"
    assert p["detections"][0]["track_id"] == 5
    assert p["persisted_ids"] == ["a", "b"]
    assert p["latency_ms"] == 12.34
    # payload must be JSON-serialisable
    assert json.loads(json.dumps(p))["runtime"] == "onnx"


@pytest.mark.asyncio
async def test_publish_vision_frame_uses_both_channels():
    from app.services.vision_stream import publish_vision_frame

    redis = MagicMock()
    redis.publish = AsyncMock(return_value=1)

    payload = {"hello": "world"}
    n = await publish_vision_frame(redis, payload, drone_id="D42")
    # per-drone channel + global channel = 2 calls
    assert redis.publish.await_count == 2
    called_channels = [c.args[0] for c in redis.publish.await_args_list]
    assert "vision.frame.all" in called_channels
    assert "vision.frame.D42" in called_channels
    assert n == 2


@pytest.mark.asyncio
async def test_publish_vision_frame_no_drone_id_only_global():
    from app.services.vision_stream import publish_vision_frame
    redis = MagicMock()
    redis.publish = AsyncMock(return_value=0)
    await publish_vision_frame(redis, {"x": 1}, drone_id=None)
    assert redis.publish.await_count == 1
    assert redis.publish.await_args_list[0].args[0] == "vision.frame.all"


@pytest.mark.asyncio
async def test_publish_vision_frame_redis_failure_is_swallowed():
    from app.services.vision_stream import publish_vision_frame
    redis = MagicMock()
    redis.publish = AsyncMock(side_effect=RuntimeError("boom"))
    # Must NOT raise — vision inference cannot block on message bus.
    n = await publish_vision_frame(redis, {"x": 1}, drone_id="D1")
    assert n == 0


@pytest.mark.asyncio
async def test_publish_vision_frame_redis_none():
    from app.services.vision_stream import publish_vision_frame
    n = await publish_vision_frame(None, {"x": 1}, drone_id="D1")
    assert n == 0


# ---------------------------------------------------------------------------
# End-to-end: /vision/infer publishes; /ws/vision/{id} receives
# ---------------------------------------------------------------------------


async def _make_operator(client, email: str = "") -> str:
    from uuid import uuid4
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    if not email:
        email = f"vs_{uuid4().hex[:10]}@x.com"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role="operator",
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    body = r.json()
    if "access_token" not in body:
        raise AssertionError(f"login failed for {email}: status={r.status_code} body={body}")
    return body["access_token"]


@pytest.mark.asyncio
async def test_infer_publishes_to_redis(client, monkeypatch):
    """/vision/infer must call redis.publish with a JSON envelope containing
    the detection payload."""
    tok = await _make_operator(client)

    calls: list[tuple[str, str]] = []

    from app.main import app as _app
    real_redis = _app.state.redis

    async def _capture_publish(channel, body):
        calls.append((channel, body))
        return 1

    monkeypatch.setattr(real_redis, "publish", _capture_publish, raising=False)

    from uuid import uuid4
    drone_uuid = str(uuid4())

    r = await client.post(
        "/api/v1/vision/infer",
        json={
            "hint": "person",
            "drone_id": drone_uuid,
            "persist": False,
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text

    # Publisher fires two channels: per-drone and global.
    channels = {c[0] for c in calls}
    assert "vision.frame.all" in channels
    assert f"vision.frame.{drone_uuid}" in channels

    # Body should be a JSON envelope with type=vision.frame.
    for _, body in calls:
        env = json.loads(body)
        assert env["type"] == "vision.frame"
        assert env["drone_id"] == drone_uuid
        assert "detections" in env
        assert "model_tag" in env


@pytest.mark.asyncio
async def test_infer_does_not_fail_when_publish_errors(client, monkeypatch):
    """If Redis publish raises, /vision/infer must still return 200."""
    tok = await _make_operator(client)

    from app.main import app as _app
    real_redis = _app.state.redis

    async def _bad_publish(channel, body):
        raise RuntimeError("redis down")
    monkeypatch.setattr(real_redis, "publish", _bad_publish, raising=False)

    from uuid import uuid4
    r = await client.post(
        "/api/v1/vision/infer",
        json={"hint": "vehicle", "drone_id": str(uuid4()), "persist": False},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert "runtime" in r.json()
