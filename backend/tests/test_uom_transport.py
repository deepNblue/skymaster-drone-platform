"""Tests for config-driven UOM transports and the report state machine."""
from __future__ import annotations

import json
import time
from uuid import uuid4

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_uom_state():
    from app.services import uom_client

    uom_client.reset_mock_transport()
    uom_client.reset_uom_config_cache()
    yield
    uom_client.reset_mock_transport()
    uom_client.reset_uom_config_cache()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_config_loads_with_airspace_library():
    from app.services.uom_client import load_uom_config

    cfg = load_uom_config()
    assert cfg["version"] == "1.0"
    airspace = cfg["mock"]["airspace"]
    assert airspace["general_ceiling_m"] == 120.0
    assert any(z["name"] == "天府国际机场净空区" for z in airspace["no_fly_zones"])
    assert cfg["report"]["expire_after_end_s"] == 3600
    assert cfg["auth"]["ak_env"] == "UOM_AK"


def test_config_path_can_be_overridden(monkeypatch, tmp_path):
    from app.services.uom_client import load_uom_config

    custom = tmp_path / "uom-custom.json"
    custom.write_text(
        json.dumps({"version": "custom", "mode": {"default": "mock"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("UOM_CONFIG", str(custom))
    assert load_uom_config()["version"] == "custom"


def test_get_mode_reads_config_default_and_env(monkeypatch):
    from app.services.uom_client import get_mode

    cfg = {"mode": {"env": "UOM_MODE", "default": "proxy",
                    "allowed": ["mock", "live", "proxy"]}}
    monkeypatch.delenv("UOM_MODE", raising=False)
    assert get_mode(cfg) == "proxy"
    monkeypatch.setenv("UOM_MODE", "live")
    assert get_mode(cfg) == "live"
    monkeypatch.setenv("UOM_MODE", "bogus")
    assert get_mode(cfg) == "proxy"


def test_config_status_never_leaks_secret_values(monkeypatch):
    from app.services.uom_client import config_status

    monkeypatch.setenv("UOM_MODE", "live")
    monkeypatch.setenv("UOM_BASE_URL", "https://uom.example.test")
    monkeypatch.setenv("UOM_AK", "AK-SECRET-VALUE")
    monkeypatch.setenv("UOM_SK", "SK-SECRET-VALUE")
    status = config_status()
    assert status["mode"] == "live"
    assert status["authorized"] is True
    assert status["ak_set"] and status["sk_set"] and status["base_url_set"]
    dumped = json.dumps(status)
    assert "AK-SECRET-VALUE" not in dumped
    assert "SK-SECRET-VALUE" not in dumped


# ---------------------------------------------------------------------------
# HTTP transport — fully offline via httpx.MockTransport
# ---------------------------------------------------------------------------


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _set_creds(monkeypatch, base="https://uom.example.test"):
    monkeypatch.setenv("UOM_BASE_URL", base)
    monkeypatch.setenv("UOM_AK", "AK-TEST")
    monkeypatch.setenv("UOM_SK", "SK-TEST")


def test_http_transport_signs_request_and_maps_reply(monkeypatch):
    from app.services.uom_client import (
        HttpUomTransport, PilotInfo, hash_id_card, verify_signature,
    )

    _set_creds(monkeypatch)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = request.content
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "uom_pilot_ref": "UP-99"})

    transport = HttpUomTransport("live", client=_mock_client(handler))
    result = transport.upsert_pilot(PilotInfo(
        pilot_id="P9", name="王五", id_card_hash=hash_id_card("510107199001011234"),
    ))
    assert result == {"ok": True, "uom_pilot_ref": "UP-99"}
    assert seen["url"] == "https://uom.example.test/uom/v1/pilots"
    ok, msg = verify_signature(
        method="POST", path="/uom/v1/pilots", body=seen["body"],
        ak="AK-TEST", sk="SK-TEST", headers=seen["headers"],
    )
    assert ok, msg


def test_http_transport_maps_airspace_and_status_aliases(monkeypatch):
    from app.services.uom_client import (
        AirspaceQuery, FlightPlan, HttpUomTransport,
    )

    _set_creds(monkeypatch)
    monkeypatch.setenv("UOM_PROXY_URL", "https://uom-proxy.example.test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("airspace/check"):
            return httpx.Response(200, json={
                "allowed": True, "zone_type": "limited", "ceiling_m": 90,
                "reason": "限高内可飞", "references": ["DOC-1"],
            })
        return httpx.Response(200, json={
            "uom_ref_no": "UOM-X1", "status": "APPROVAL_PASSED",
            "valid_from": "2026-01-01T00:00:00+08:00",
            "valid_to": "2026-01-01T02:00:00+08:00",
        })

    transport = HttpUomTransport("proxy", client=_mock_client(handler))
    verdict = transport.check_airspace(
        AirspaceQuery(lat=22.5, lng=113.9, altitude_m=80)
    )
    assert verdict.allowed is True
    assert verdict.zone_type == "limited"
    assert verdict.ceiling_m == 90
    assert verdict.references == ["DOC-1"]

    ack = transport.submit_plan(FlightPlan(
        plan_id="P-X", pilot_id="P9", aircraft_reg="UAS-X",
        lat=22.5, lng=113.9, altitude_m=80,
        start_ts="2026-01-01T00:00:00+08:00",
        end_ts="2026-01-01T02:00:00+08:00",
        purpose="巡检", contact_phone="13800000000", attachments=[],
    ))
    assert ack.status == "accepted"
    assert ack.uom_ref_no == "UOM-X1"


def test_http_transport_requires_credentials(monkeypatch):
    from app.services.uom_client import (
        AirspaceQuery, HttpUomTransport, UomConfigurationError,
    )

    _set_creds(monkeypatch)
    monkeypatch.delenv("UOM_SK", raising=False)
    transport = HttpUomTransport(
        "live", client=_mock_client(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(UomConfigurationError, match="UOM_SK"):
        transport.check_airspace(AirspaceQuery(lat=22.5, lng=113.9, altitude_m=80))


def test_http_transport_requires_base_url(monkeypatch):
    from app.services.uom_client import (
        AirspaceQuery, HttpUomTransport, UomConfigurationError,
    )

    _set_creds(monkeypatch)
    monkeypatch.delenv("UOM_BASE_URL", raising=False)
    transport = HttpUomTransport(
        "live", client=_mock_client(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(UomConfigurationError, match="UOM_BASE_URL"):
        transport.check_airspace(AirspaceQuery(lat=22.5, lng=113.9, altitude_m=80))


def test_http_transport_retries_then_succeeds(monkeypatch):
    from app.services.uom_client import HttpUomTransport, PilotInfo, hash_id_card

    _set_creds(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True, "uom_pilot_ref": "UP-R"})

    transport = HttpUomTransport("live", client=_mock_client(handler))
    result = transport.upsert_pilot(PilotInfo("P-R", "赵六", hash_id_card("110108198505050505")))
    assert result["ok"] is True
    assert calls["n"] == 2


def test_client_selects_transport_by_mode(monkeypatch):
    from app.services.uom_client import (
        HttpUomTransport, MockUomTransport, UomClient,
    )

    monkeypatch.setenv("UOM_MODE", "proxy")
    assert isinstance(UomClient()._transport, HttpUomTransport)
    monkeypatch.setenv("UOM_MODE", "mock")
    assert isinstance(UomClient()._transport, MockUomTransport)


# ---------------------------------------------------------------------------
# Report state machine — EXPIRED is now reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_expires_to_terminal_state(tmp_path):
    from app.services.uom_adapter import ReportStatus, UOMAdapter

    adapter = UOMAdapter(
        db_path=tmp_path / "uom.db", auto_approve=False, approval_delay_s=1,
    )
    await adapter.start()
    try:
        now = time.time()
        report = await adapter.submit(
            operator_id="org-exp", pilot_name="p", aircraft_reg="UAS-EXP",
            purpose="test",
            area_polygon=[[113.9, 22.5], [114.0, 22.5], [114.0, 22.6]],
            max_alt_m=100, start_ts=now - 7200, end_ts=now - 7140,
        )
        await adapter.approve(report.id)
        assert report.status == ReportStatus.APPROVED

        changed = await adapter.expire_stale(now_ts=now)
        assert [r.id for r in changed] == [report.id]
        assert report.status == ReportStatus.EXPIRED
        # Idempotent: no second transition.
        assert await adapter.expire_stale(now_ts=now) == []
        assert (await adapter.get(report.id)).status == ReportStatus.EXPIRED
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_expire_endpoint_and_states_inventory(client):
    states = await client.get("/api/v1/uom/states")
    assert states.status_code == 200
    body = states.json()
    assert "expired" in body["states"]
    assert "expire_after_end_s" in body["config"]

    expired = await client.post("/api/v1/uom/reports/expire")
    assert expired.status_code == 200
    assert "expired_count" in expired.json()
    assert "expired" in expired.json()["counts"]


@pytest.mark.asyncio
async def test_status_endpoint_exposes_config_not_secrets(client):
    from app.services.auth import create_access_token
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    email = f"uom-status-{uuid4().hex[:8]}@x.com"
    async with Session() as s:
        s.add(User(id=uuid4(), email=email,
                   hashed_pw=hash_password("StrongPassW0rd#"), role="admin"))
        await s.commit()
    login = await client.post("/api/v1/auth/login",
                              json={"email": email, "password": "StrongPassW0rd#"})
    token = login.json()["access_token"]
    r = await client.get("/api/v1/uom/status",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("mock", "live", "proxy")
    assert body["config_version"] == "1.0"
    assert "paths" in body and "signature" in body
