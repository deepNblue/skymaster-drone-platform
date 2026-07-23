"""Tests for R21 Step B — Copilot command bus (execute=True path)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Pure bus tests — no HTTP, no DB
# ---------------------------------------------------------------------------


def test_bus_is_executable_map():
    from app.services.copilot_bus import is_executable
    assert is_executable("drone.command.takeoff")
    assert is_executable("drone.command.goto")
    assert is_executable("drone.command.rth")
    # Not wired → false
    assert not is_executable("mission.recording.start")
    assert not is_executable("unknown.tool")


def test_bus_denies_non_operator_role():
    from app.services.copilot_bus import execute_tool_call
    viewer = SimpleNamespace(role="viewer")
    result = execute_tool_call(
        {"tool": "drone.command.takeoff", "args": {}},
        actor=viewer,
    )
    assert result["status"] == "denied"
    assert "无权" in result["detail"]


def test_bus_noop_on_empty_call():
    from app.services.copilot_bus import execute_tool_call
    operator = SimpleNamespace(role="operator")
    assert execute_tool_call({}, actor=operator)["status"] == "noop"
    assert execute_tool_call({"tool": ""}, actor=operator)["status"] == "noop"


def test_bus_planned_marker_for_unrouted_tool():
    """Known tool with no sim wire → 'planned' marker, not an error."""
    from app.services.copilot_bus import execute_tool_call
    operator = SimpleNamespace(role="operator")
    result = execute_tool_call(
        {"tool": "mission.recording.start", "args": {}},
        actor=operator,
    )
    assert result["status"] == "planned"


def test_bus_error_when_no_drone_port(monkeypatch):
    from app.services.copilot_bus import execute_tool_call
    monkeypatch.delenv("SIM_DRONES", raising=False)
    monkeypatch.delenv("COPILOT_SIM_PORT_MAP", raising=False)
    operator = SimpleNamespace(role="operator")
    result = execute_tool_call(
        {"tool": "drone.command.rth", "args": {}},
        actor=operator,
    )
    assert result["status"] == "error"
    assert "端口" in result["detail"] or "SIM_DRONES" in result["detail"]


def test_bus_unreachable_sim_returns_structured_error(monkeypatch):
    """When the port is set but no server listens → bus must return
    ``{status: error}`` rather than raising, so the turn still gets saved."""
    from app.services.copilot_bus import execute_tool_call
    monkeypatch.setenv("SIM_DRONES", "1:1")   # port 1 = privileged, will refuse
    operator = SimpleNamespace(role="operator")
    result = execute_tool_call(
        {"tool": "drone.command.rth", "args": {}},
        actor=operator,
    )
    assert result["status"] == "error"


def test_bus_dispatches_goto_via_stubbed_urlopen(monkeypatch):
    """Confirm the bus hits the /goto endpoint with the transformed body."""
    from app.services import copilot_bus

    captured: dict = {}

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def _fake_urlopen(req, timeout=3):
        captured["url"] = req.full_url
        captured["body"] = req.data.decode()
        return _FakeResp()

    monkeypatch.setattr(copilot_bus.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setenv("SIM_DRONES", "1:15001")

    operator = SimpleNamespace(role="operator")
    result = copilot_bus.execute_tool_call(
        {"tool": "drone.command.goto", "args": {"lat": 30.5, "lng": 104.06, "alt": 120}},
        actor=operator,
    )
    assert result["status"] == "ok"
    assert "127.0.0.1:15001/goto" in captured["url"]
    assert '"lat": 30.5' in captured["body"]
    assert '"lng": 104.06' in captured["body"]
    assert '"alt": 120' in captured["body"]


# ---------------------------------------------------------------------------
# API-level end-to-end — hitting POST /copilot/sessions/{sid}/turns
# ---------------------------------------------------------------------------


async def _make_operator(client, email: str, role: str = "operator") -> str:
    from uuid import uuid4
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

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
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_execute_true_records_tool_result(client, monkeypatch):
    """execute=True → turn.tool_result is populated by the bus.

    Since we don't run a FakeDrone in tests, the bus returns
    ``{status: error, detail: 'sim unreachable'}`` — that's still a valid
    tool_result and the turn must be saved with status='error'.
    """
    monkeypatch.setenv("SIM_DRONES", "1:1")  # port 1 refuses connections

    tok = await _make_operator(client, "cb_exec@x.com")
    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"title": "bus-test"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    sid = r.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "返航", "execute": True},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "return_home"
    assert body["tool_result"] is not None
    assert body["tool_result"]["status"] == "error"
    assert body["status"] == "error"


@pytest.mark.asyncio
async def test_execute_false_leaves_tool_result_none(client, monkeypatch):
    """Default execute=False → tool_result stays None even for wired tools."""
    monkeypatch.setenv("SIM_DRONES", "1:1")

    tok = await _make_operator(client, "cb_plan@x.com")
    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"title": "plan-only"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    sid = r.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "返航"},  # execute defaults False
        headers={"Authorization": f"Bearer {tok}"},
    )
    body = r.json()
    assert body["intent"] == "return_home"
    assert body["tool_call"]["tool"] == "drone.command.rth"
    assert body["tool_result"] is None
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_execute_true_denied_for_viewer(client, monkeypatch):
    """Viewer role → bus returns denied, turn saved with status='denied'."""
    monkeypatch.setenv("SIM_DRONES", "1:15001")

    tok = await _make_operator(client, "cb_viewer@x.com", role="viewer")
    r = await client.post(
        "/api/v1/copilot/sessions",
        json={"title": "viewer-test"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    sid = r.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/sessions/{sid}/turns",
        json={"text": "起飞", "execute": True},
        headers={"Authorization": f"Bearer {tok}"},
    )
    body = r.json()
    assert body["tool_result"]["status"] == "denied"
    assert body["status"] == "denied"
