"""Tests for R20 Track B — Vision AI runtime + Copilot intent parser."""
from __future__ import annotations

from uuid import uuid4

import pytest


# ==========================================================================
# Vision runtime — pure module tests (no DB)
# ==========================================================================


def test_vision_runtime_registry_has_mock():
    from app.services.vision_runtime import list_runtimes
    names = list_runtimes()
    assert "mock" in names
    assert "onnx" in names


@pytest.mark.asyncio
async def test_mock_runtime_deterministic():
    """Same image → same detections."""
    from app.services.vision_runtime import MockVisionRuntime
    rt = MockVisionRuntime()
    r1 = await rt.infer(b"same-image-bytes", frame_idx=1)
    r2 = await rt.infer(b"same-image-bytes", frame_idx=1)
    assert [d.label for d in r1.detections] == [d.label for d in r2.detections]
    assert [d.confidence for d in r1.detections] == [d.confidence for d in r2.detections]


@pytest.mark.asyncio
async def test_mock_runtime_hint_bias():
    """When a hint label is passed, most detections should carry that label."""
    from app.services.vision_runtime import MockVisionRuntime
    rt = MockVisionRuntime()
    labels: list[str] = []
    for i in range(30):
        r = await rt.infer(f"frame-{i}".encode(), hint="fire", frame_idx=i)
        labels.extend(d.label for d in r.detections)
    if labels:
        # Skewed but not required to be pure fire.
        ratio = labels.count("fire") / len(labels)
        assert ratio > 0.3, f"hint bias too weak: {ratio:.2f}"


def test_decode_base64_image_data_url():
    from app.services.vision_runtime import decode_base64_image
    raw = b"hello-image"
    import base64
    b64 = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert decode_base64_image(b64) == raw


# ==========================================================================
# Copilot intent parser — pure module tests
# ==========================================================================


@pytest.mark.parametrize("text,expected", [
    ("起飞", "takeoff"),
    ("takeoff please", "takeoff"),
    ("赶紧降落", "land"),
    ("return home now", "return_home"),
    ("返航", "return_home"),
    ("hover please", "hover"),
    ("悬停", "hover"),
    ("开始录像", "start_recording"),
    ("stop recording", "stop_recording"),
    ("生成报告", "generate_report"),
    ("你能做什么", "help"),
    ("状态", "status"),
])
def test_parse_intent_keywords(text, expected):
    from app.services.copilot_intent import parse_intent
    parsed = parse_intent(text)
    assert parsed.intent == expected
    assert parsed.confidence >= 0.9


def test_parse_intent_goto_extracts_coords():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("去 30.5,104.06,120")
    assert p.intent == "goto_waypoint"
    assert p.args["lat"] == 30.5
    assert p.args["lng"] == 104.06
    assert p.args["alt"] == 120
    assert p.confidence >= 0.8


def test_parse_intent_goto_english():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("goto 30.5,104.06")
    assert p.intent == "goto_waypoint"
    assert "alt" not in p.args


def test_parse_intent_vision_query():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("看到 person 了吗")
    assert p.intent == "vision_query"
    assert p.args["label"] == "person"


def test_parse_intent_unknown_returns_clarify():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("完全不知所云 12345 xyz")
    assert p.intent == "unknown"
    assert p.confidence == 0.0
    assert p.clarify


def test_parse_intent_empty():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("")
    assert p.intent == "noop"


def test_plan_tool_call_maps_intents():
    from app.services.copilot_intent import parse_intent, plan_tool_call
    p = parse_intent("起飞")
    call = plan_tool_call(p, drone_id="d1")
    assert call["tool"] == "drone.command.takeoff"
    assert call["drone_id"] == "d1"

    p = parse_intent("去 30,104")
    call = plan_tool_call(p)
    assert call["tool"] == "drone.command.goto"
    assert call["args"] == {"lat": 30.0, "lng": 104.0}


def test_plan_tool_call_none_for_low_confidence():
    from app.services.copilot_intent import parse_intent, plan_tool_call
    p = parse_intent("abcxyz gibberish")
    assert plan_tool_call(p) is None


def test_render_reply_goto_formats_coords():
    from app.services.copilot_intent import parse_intent, render_reply
    p = parse_intent("去 30.5,104.06,120")
    reply = render_reply(p)
    assert "30.5" in reply
    assert "104.06" in reply
    assert "120" in reply


def test_run_turn_end_to_end():
    from app.services.copilot_intent import run_turn
    out = run_turn("起飞", drone_id="d1")
    assert out["intent"] == "takeoff"
    assert out["tool_call"]["tool"] == "drone.command.takeoff"
    assert out["status"] == "ok"
    assert out["latency_ms"] >= 0


# ==========================================================================
# API endpoints
# ==========================================================================


async def _login_user(client, email: str = "") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from uuid import uuid4
    from sqlalchemy.ext.asyncio import async_sessionmaker

    if not email:
        email = f"vr_{uuid4().hex[:10]}@x.com"
    from sqlalchemy.ext.asyncio import async_sessionmaker

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
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_vision_runtimes_endpoint(client):
    tok = await _login_user(client)
    r = await client.get(
        "/api/v1/vision/runtimes",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "mock" in body["available"]
    assert body["active"] in body["available"]


@pytest.mark.asyncio
async def test_vision_infer_returns_detections(client):
    import base64
    tok = await _login_user(client)
    b64 = "data:image/png;base64," + base64.b64encode(b"deterministic-frame").decode()
    r = await client.post(
        "/api/v1/vision/infer",
        json={"image_b64": b64, "hint": "person", "persist": False},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runtime"] == "mock"
    assert isinstance(body["detections"], list)


@pytest.mark.asyncio
async def test_vision_infer_persists_high_confidence(client):
    import base64
    tok = await _login_user(client)
    # Build 10 different frames — some will produce hi-conf detections.
    persisted_ids: list[str] = []
    for i in range(20):
        b64 = "data:image/png;base64," + base64.b64encode(f"frame-{i}".encode()).decode()
        r = await client.post(
            "/api/v1/vision/infer",
            json={"image_b64": b64, "persist": True, "frame_idx": i},
            headers={"Authorization": f"Bearer {tok}"},
        )
        persisted_ids.extend(r.json()["persisted"])
    # Very likely at least one detection ≥ 0.65 across 20 frames.
    assert len(persisted_ids) >= 1


@pytest.mark.asyncio
async def test_copilot_dry_run(client):
    tok = await _login_user(client)
    r = await client.post(
        "/api/v1/copilot/dry-run",
        json={"text": "去 30.5,104.06"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "goto_waypoint"
    assert body["args"]["lat"] == 30.5
    assert body["tool_call"]["tool"] == "drone.command.goto"


@pytest.mark.asyncio
async def test_copilot_session_and_turns(client):
    tok = await _login_user(client)
    # Create session
    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"title": "巡检-001", "persona": "operator"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # Two turns
    for text in ("起飞", "去 30,104"):
        r = await client.post(
            f"/api/v1/copilot/sessions/{sid}/turns",
            json={"text": text},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text

    # List turns
    r = await client.get(
        f"/api/v1/copilot/sessions/{sid}/turns",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    turns = r.json()
    assert len(turns) == 2
    assert turns[0]["intent"] == "takeoff"
    assert turns[1]["intent"] == "goto_waypoint"


@pytest.mark.asyncio
async def test_copilot_session_scope_isolated(client):
    """User A's session cannot be read by user B."""
    tok_a = await _login_user(client)
    tok_b = await _login_user(client)

    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"title": "A的会话"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    sid = r.json()["id"]

    r = await client.get(
        f"/api/v1/copilot/sessions/{sid}/turns",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r.status_code == 404
