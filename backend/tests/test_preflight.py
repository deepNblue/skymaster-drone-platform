"""Tests for v2.0 Track A A3 — Pre-flight combined check."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset():
    from app.services import rate_limit, uom_client
    rate_limit.reset_bucket()
    uom_client.reset_mock_transport()
    yield
    rate_limit.reset_bucket()
    uom_client.reset_mock_transport()


def _now(hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _make_user(client, role="operator") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = f"pf_{role}_{uuid4().hex[:10]}@x.com"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(id=uuid4(), email=email,
                    hashed_pw=hash_password("StrongPassW0rd#"), role=role))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Rule-level tests
# ---------------------------------------------------------------------------


def test_airspace_rule_flags_no_fly():
    from app.api.v1.preflight import _rule_airspace, PreflightIn
    body = PreflightIn(
        lat=30.578, lng=103.947, altitude_m=50,  # 双流机场
        start_ts=_now(), end_ts=_now(2),
    )
    r = _rule_airspace(body)
    assert r.status == "fail"


def test_weather_rule_warns_when_missing():
    from app.api.v1.preflight import _rule_weather, PreflightIn
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,
        start_ts=_now(), end_ts=_now(1),
    )
    r = _rule_weather(body)
    assert r.status == "warn"


def test_weather_rule_fails_on_high_wind():
    from app.api.v1.preflight import _rule_weather, PreflightIn
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,
        start_ts=_now(), end_ts=_now(1),
        wind_speed_ms=15.0, visibility_m=5000, precipitation_mmph=0,
    )
    r = _rule_weather(body)
    assert r.status == "fail"
    assert "风速" in r.detail


def test_airworthiness_fail_if_overdue():
    from app.api.v1.preflight import _rule_airworthiness, PreflightIn
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,
        start_ts=_now(), end_ts=_now(1),
        last_maintenance_at=(datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),
    )
    r = _rule_airworthiness(body)
    assert r.status == "fail"


def test_pilot_rule_fail_if_expired():
    from app.api.v1.preflight import _rule_pilot, PreflightIn
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,
        start_ts=_now(), end_ts=_now(1),
        license_expires_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
    )
    r = _rule_pilot(body)
    assert r.status == "fail"


def test_tod_rule_warns_at_night():
    from app.api.v1.preflight import _rule_time_of_day, PreflightIn
    # 明确构造一个 22:00 UTC 起飞
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,
        start_ts="2026-07-11T22:00:00+00:00",
        end_ts="2026-07-11T23:00:00+00:00",
    )
    r = _rule_time_of_day(body)
    assert r.status == "warn"
    assert "夜航" in r.detail


def test_aggregate_verdict():
    from app.api.v1.preflight import run_preflight, PreflightIn
    body = PreflightIn(
        lat=27, lng=100, altitude_m=80,  # 正常空域
        start_ts="2026-07-11T09:00:00+00:00",
        end_ts="2026-07-11T11:00:00+00:00",
        wind_speed_ms=5, visibility_m=8000, precipitation_mmph=0,
        last_maintenance_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        license_expires_at=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
        battery_cycles=50,
    )
    out = run_preflight(body)
    assert out.verdict == "go"
    assert out.fail_count == 0


def test_verdict_no_go_when_any_fail():
    from app.api.v1.preflight import run_preflight, PreflightIn
    body = PreflightIn(
        lat=30.578, lng=103.947, altitude_m=50,  # 机场禁飞区
        start_ts="2026-07-11T09:00:00+00:00",
        end_ts="2026-07-11T11:00:00+00:00",
        wind_speed_ms=5, visibility_m=8000, precipitation_mmph=0,
        last_maintenance_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        license_expires_at=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
    )
    out = run_preflight(body)
    assert out.verdict == "no_go"
    assert out.fail_count >= 1


# ---------------------------------------------------------------------------
# API test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_endpoint_go(client):
    tok = await _make_user(client)
    r = await client.post(
        "/api/v1/preflight/check",
        json={
            "lat": 27, "lng": 100, "altitude_m": 80,
            "start_ts": "2026-07-11T09:00:00+00:00",
            "end_ts": "2026-07-11T11:00:00+00:00",
            "wind_speed_ms": 5, "visibility_m": 8000,
            "precipitation_mmph": 0,
            "last_maintenance_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "license_expires_at": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
            "battery_cycles": 40,
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "go"
    assert body["fail_count"] == 0
    assert len(body["rules"]) == 6


@pytest.mark.asyncio
async def test_preflight_endpoint_no_go_in_no_fly_zone(client):
    tok = await _make_user(client)
    r = await client.post(
        "/api/v1/preflight/check",
        json={
            "lat": 30.578, "lng": 103.947, "altitude_m": 50,
            "start_ts": "2026-07-11T09:00:00+00:00",
            "end_ts": "2026-07-11T11:00:00+00:00",
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "no_go"
