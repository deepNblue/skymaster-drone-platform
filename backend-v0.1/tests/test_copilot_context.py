"""Tests for R21 Step G — Copilot multi-turn context."""
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


# ---------------------------------------------------------------------------
# Pure resolver tests
# ---------------------------------------------------------------------------


def test_alt_delta_positive_climbs():
    from app.services.copilot_intent import parse_intent
    p = parse_intent("再飞高 20m")
    assert p.intent == "goto_waypoint"
    assert p.args.get("alt_delta") == 20.0


def test_alt_delta_negative_descends():
    from app.services.copilot_intent import parse_intent
    for phrase in ("再降 30m", "descend 15m", "下降 10 米", "go down 5"):
        p = parse_intent(phrase)
        assert p.intent == "goto_waypoint", phrase
        assert p.args.get("alt_delta") is not None
        assert p.args["alt_delta"] < 0, phrase


def test_back_reference_matches_previous_position():
    from app.services.copilot_intent import parse_intent
    for phrase in ("回到刚才的位置", "回刚才的坐标", "回到之前的地点"):
        p = parse_intent(phrase)
        assert p.intent == "goto_waypoint", phrase
        assert p.args == {} or "lat" not in p.args


def test_apply_context_fills_drone_id_and_coords():
    from app.services.copilot_intent import parse_intent
    from app.services.copilot_context import apply_context, ContextState

    ctx = ContextState(
        drone_id="D-alpha", last_lat=30.5, last_lng=104.06, last_alt=120.0,
        turn_idx=1,
    )
    p = parse_intent("回到刚才的位置")
    r = apply_context(p, ctx)
    assert r.args["drone_id"] == "D-alpha"
    assert r.args["lat"] == 30.5
    assert r.args["lng"] == 104.06
    # confidence should be bumped after successful backfill
    assert r.confidence > p.confidence
    assert "drone_id" in r.args["resolved_from"]


def test_apply_context_computes_absolute_alt_from_delta():
    from app.services.copilot_intent import parse_intent
    from app.services.copilot_context import apply_context, ContextState

    ctx = ContextState(
        drone_id="D-b", last_lat=30.0, last_lng=104.0, last_alt=100.0,
    )
    p = parse_intent("再飞高 20m")
    r = apply_context(p, ctx)
    assert r.args["alt"] == 120.0
    assert r.args["alt_delta"] == 20.0
    assert "alt(via delta)" in r.args["resolved_from"]


def test_apply_context_does_not_invent_missing_state():
    """If no prior turn set a drone / position, the resolver must NOT
    hallucinate one — the ambiguous parse stays ambiguous."""
    from app.services.copilot_intent import parse_intent
    from app.services.copilot_context import apply_context, ContextState

    p = parse_intent("回到刚才的位置")
    r = apply_context(p, ContextState())
    assert r.args == {} or "lat" not in r.args
    assert r.confidence == p.confidence


def test_return_home_backfills_drone_id_only():
    from app.services.copilot_intent import parse_intent
    from app.services.copilot_context import apply_context, ContextState

    ctx = ContextState(drone_id="D-rh", last_lat=1, last_lng=2, last_alt=3)
    p = parse_intent("返航")
    r = apply_context(p, ctx)
    assert r.args.get("drone_id") == "D-rh"
    # We must NOT stuff lat/lng into a return_home command.
    assert "lat" not in r.args
    assert "lng" not in r.args


# ---------------------------------------------------------------------------
# End-to-end — chat over 3 turns
# ---------------------------------------------------------------------------


async def _make_operator(client, email: str) -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
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
async def test_multi_turn_backfills_from_prior_turn(client):
    tok = await _make_operator(client, "ctx_e2e@x.com")
    h = {"Authorization": f"Bearer {tok}"}

    # Create session.
    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"drone_id": None, "title": "R21 G test"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # T1: full-form goto.
    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "飞到 30.5, 104.06, 120"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    t1 = r.json()
    assert t1["intent"] == "goto_waypoint"
    assert t1["args"]["lat"] == 30.5
    assert t1["args"]["alt"] == 120.0

    # T2: altitude delta — expect ctx.last_alt (120) + 20 = 140.
    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "再飞高 20m"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    t2 = r.json()
    assert t2["intent"] == "goto_waypoint"
    assert t2["args"]["alt"] == 140.0
    assert t2["args"]["lat"] == 30.5
    assert t2["args"]["lng"] == 104.06
    assert "resolved_from" in t2["args"]

    # T3: pure back-reference.
    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "回到刚才的位置"},
        headers=h,
    )
    assert r.status_code == 200
    t3 = r.json()
    # After T2 the last altitude is 140.
    assert t3["args"]["alt"] == 140.0
    assert t3["args"]["lat"] == 30.5
    assert t3["args"]["lng"] == 104.06
