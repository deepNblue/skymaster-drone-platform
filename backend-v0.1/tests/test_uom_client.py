"""Tests for v2.0 Track A A3 — UOM client & endpoints."""
from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket_and_uom():
    from app.services import rate_limit
    from app.services import uom_client
    rate_limit.reset_bucket()
    uom_client.reset_mock_transport()
    yield
    rate_limit.reset_bucket()
    uom_client.reset_mock_transport()


# ---------------------------------------------------------------------------
# Pure signer tests
# ---------------------------------------------------------------------------


def test_sign_and_verify_roundtrip():
    from app.services.uom_client import sign_request, verify_signature
    body = b'{"foo":"bar"}'
    hdr = sign_request(method="POST", path="/uom/v1/x", body=body,
                        ak="AK", sk="SK")
    ok, msg = verify_signature(
        method="POST", path="/uom/v1/x", body=body,
        ak="AK", sk="SK", headers=hdr,
    )
    assert ok, msg


def test_verify_rejects_tampered_body():
    from app.services.uom_client import sign_request, verify_signature
    body = b'{"foo":"bar"}'
    hdr = sign_request(method="POST", path="/x", body=body, ak="AK", sk="SK")
    ok, msg = verify_signature(
        method="POST", path="/x", body=b'{"foo":"baz"}',
        ak="AK", sk="SK", headers=hdr,
    )
    assert not ok


def test_verify_rejects_skewed_timestamp():
    from app.services.uom_client import sign_request, verify_signature
    body = b'{}'
    hdr = sign_request(method="POST", path="/x", body=body, ak="AK", sk="SK",
                       ts="1000000000")  # Sep 2001 — very stale
    ok, _ = verify_signature(
        method="POST", path="/x", body=body,
        ak="AK", sk="SK", headers=hdr, max_skew_s=60,
    )
    assert not ok


def test_hash_id_card_stable():
    from app.services.uom_client import hash_id_card
    h1 = hash_id_card("510107199001011234")
    h2 = hash_id_card("  510107199001011234  ")
    assert h1 == h2 and len(h1) == 64


# ---------------------------------------------------------------------------
# Mock transport behavior
# ---------------------------------------------------------------------------


def test_mock_airspace_prohibited_near_airport():
    from app.services.uom_client import (
        AirspaceQuery, UomClient,
    )
    c = UomClient(mode="mock")
    # 双流机场附近
    v = c.check_airspace(AirspaceQuery(lat=30.578, lng=103.947, altitude_m=50))
    assert v.allowed is False
    assert v.zone_type == "prohibited"
    assert "净空" in v.reason or "机场" in v.reason


def test_mock_airspace_120m_default_ceiling():
    from app.services.uom_client import AirspaceQuery, UomClient
    c = UomClient(mode="mock")
    # 远离已知管控区的位置 + 150m
    v = c.check_airspace(AirspaceQuery(lat=27.0, lng=100.0, altitude_m=150))
    assert v.allowed is False
    assert "120m" in v.reason


def test_mock_airspace_allows_normal_flight():
    from app.services.uom_client import AirspaceQuery, UomClient
    c = UomClient(mode="mock")
    v = c.check_airspace(AirspaceQuery(lat=27.0, lng=100.0, altitude_m=80))
    assert v.allowed is True
    assert v.zone_type == "normal"


def test_mock_submit_plan_requires_registered_pilot():
    from app.services.uom_client import (
        FlightPlan, UomClient,
    )
    c = UomClient(mode="mock")
    ack = c.submit_plan(FlightPlan(
        plan_id="P1", pilot_id="P-unknown", aircraft_reg="UAS-1",
        lat=27.0, lng=100.0, altitude_m=80,
        start_ts="2026-07-11T09:00:00+08:00",
        end_ts="2026-07-11T11:00:00+08:00",
        purpose="巡线", contact_phone="13800000000", attachments=[],
    ))
    assert ack.status == "rejected"
    assert "实名" in (ack.reason or "")


def test_mock_end_to_end_accept():
    from app.services.uom_client import (
        AircraftInfo, FlightPlan, PilotInfo, UomClient, hash_id_card,
    )
    c = UomClient(mode="mock")
    c.register_pilot(PilotInfo(
        pilot_id="P1", name="张三",
        id_card_hash=hash_id_card("510107199001011234"),
        license_no="LIC-001", license_class="视距内",
    ))
    c.register_aircraft(AircraftInfo(
        reg_no="UAS-77", manufacturer="DJI", model="M300",
        serial="SN-1", mtow_kg=6.3, category="小",
    ))
    ack = c.submit_plan(FlightPlan(
        plan_id="P-ok", pilot_id="P1", aircraft_reg="UAS-77",
        lat=27.0, lng=100.0, altitude_m=80,
        start_ts="2026-07-11T09:00:00+08:00",
        end_ts="2026-07-11T11:00:00+08:00",
        purpose="巡线", contact_phone="13800000000", attachments=[],
    ))
    assert ack.status == "accepted"
    assert ack.uom_ref_no.startswith("UOM-")
    # Round-trip fetch
    plan = c.get_plan(ack.uom_ref_no)
    assert plan is not None
    assert plan["plan"]["pilot_id"] == "P1"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def _make_user(client, role: str = "operator") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = f"uom_{role}_{uuid4().hex[:10]}@x.com"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_uom_status_returns_mode(client):
    tok = await _make_user(client)
    r = await client.get(
        "/api/v1/uom/status",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "mock"
    assert body["authorized"] is False


@pytest.mark.asyncio
async def test_viewer_cannot_register_pilot(client):
    tok = await _make_user(client, role="viewer")
    r = await client.post(
        "/api/v1/uom/pilots",
        json={
            "pilot_id": "P1", "name": "张三",
            "id_card": "510107199001011234",
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_full_flow_via_api(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/uom/pilots",
        json={
            "pilot_id": "P1", "name": "李四",
            "id_card": "110108198505050505",
            "license_no": "LIC-100", "license_class": "超视距",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = await client.post(
        "/api/v1/uom/aircrafts",
        json={
            "reg_no": "UAS-A1", "manufacturer": "极飞", "model": "V50",
            "serial": "SN-1", "mtow_kg": 15.0, "category": "小",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/v1/uom/airspace/check",
        json={"lat": 27.0, "lng": 100.0, "altitude_m": 80},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["allowed"] is True

    r = await client.post(
        "/api/v1/uom/flight-plans",
        json={
            "plan_id": "P-a1", "pilot_id": "P1", "aircraft_reg": "UAS-A1",
            "lat": 27.0, "lng": 100.0, "altitude_m": 80,
            "start_ts": "2026-07-11T09:00:00+08:00",
            "end_ts": "2026-07-11T11:00:00+08:00",
            "purpose": "植保", "contact_phone": "13800000001",
        },
        headers=h,
    )
    assert r.status_code == 200
    ack = r.json()
    assert ack["status"] == "accepted"

    r = await client.get(
        f"/api/v1/uom/flight-plans/{ack['uom_ref_no']}",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["plan"]["pilot_id"] == "P1"


@pytest.mark.asyncio
async def test_airspace_rejects_over_airport(client):
    tok = await _make_user(client)
    r = await client.post(
        "/api/v1/uom/airspace/check",
        json={"lat": 30.578, "lng": 103.947, "altitude_m": 50},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is False
    assert body["zone_type"] == "prohibited"
