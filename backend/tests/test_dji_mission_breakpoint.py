"""Breakpoint resume tests for DJI flight tasks (config-driven)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.dji_cloud_connector import (
    DJICloudConnector, METHOD_TASK_PROGRESS,
)

SN = "MOCKM300-01"
WPS = [
    {"lat": 22.81, "lng": 108.31},
    {"lat": 22.82, "lng": 108.32},
    {"lat": 22.83, "lng": 108.33},
]


@pytest.fixture
def conn():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    return c


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)
    return TestClient(app)


@pytest.fixture
def mock_connector():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = c
    yield c
    if old is None and hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    else:
        app.state.dji_connector = old


def feed(conn, data):
    msg = SimpleNamespace(
        topic="thing/product/TESTDOCK/services",
        payload=json.dumps({
            "method": METHOD_TASK_PROGRESS, "data": data,
        }).encode("utf-8"),
    )
    conn._on_mqtt_message(None, None, msg)


def prepare_and_fly(conn, ticks=2):
    tid = conn.create_mission(SN, WPS)
    conn.flighttask_execute(tid, "f-1")
    for _ in range(ticks):
        conn.mock_tick(1.0)
    return tid


def test_breakpoint_config_loaded(conn):
    cfg = conn._mission_cfg()
    assert "waypoint_index" in cfg["breakpoint_fields"]
    assert cfg["resume_field"] == "resume_from_waypoint"
    assert cfg["breakpoint_stale_s"] > 0


def test_pause_records_local_breakpoint(conn):
    tid = prepare_and_fly(conn, 2)
    conn.flighttask_pause(tid)
    slot = conn._missions[tid]
    assert slot["breakpoint"] == 2
    assert slot["breakpoint_source"] == "local"
    assert slot["breakpoint_at"] > 0


def test_device_progress_overrides_and_never_regresses(conn):
    tid = prepare_and_fly(conn, 1)
    feed(conn, {"task_id": tid, "waypoint_index": 3, "state": "running"})
    slot = conn._missions[tid]
    assert slot["breakpoint"] == 3
    assert slot["breakpoint_source"] == "device"
    feed(conn, {"task_id": tid, "waypoint_index": 1, "state": "running"})
    assert slot["breakpoint"] == 3


def test_custom_field_offset_and_resume_field(tmp_path):
    cfg_path = tmp_path / "cfg.json"
    cfg = {"mission": {
        "breakpoint_fields": ["wp"], "breakpoint_offset": 1,
        "resume_field": "resume_wp",
    }}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    c = DJICloudConnector(
        mode="mock", mission_config_path=str(cfg_path))
    c.connect()
    tid = c.create_mission(SN, WPS)
    feed(c, {"task_id": tid, "wp": 4})
    assert c._missions[tid]["breakpoint"] == 3
    sent = []
    c.on_message = lambda topic, msg: sent.append(msg)
    c.flighttask_pause(tid)
    assert c.flighttask_resume(tid)
    assert sent[-1]["data"]["resume_wp"] == 3


def test_resume_sends_configured_field(conn):
    tid = prepare_and_fly(conn, 2)
    conn.flighttask_pause(tid)
    sent = []
    conn.on_message = lambda topic, msg: sent.append(msg)
    assert conn.flighttask_resume(tid)
    assert sent[-1]["data"]["resume_from_waypoint"] == 2
    assert conn._missions[tid]["state"] == "running"
    assert conn._missions[tid]["resume_from"] == 2


def test_manual_resume_from_overrides_breakpoint(conn):
    tid = prepare_and_fly(conn, 2)
    conn.flighttask_pause(tid)
    sent = []
    conn.on_message = lambda topic, msg: sent.append(msg)
    conn.flighttask_resume(tid, resume_from=1)
    assert sent[-1]["data"]["resume_from_waypoint"] == 1
    assert conn._missions[tid]["breakpoint_source"] == "manual"


def test_breakpoint_status_staleness_and_filters(conn):
    tid = prepare_and_fly(conn, 1)
    conn.flighttask_pause(tid)
    st = conn.breakpoint_status(task_id=tid)
    assert st["breakpoints"][0]["stale"] is False
    assert st["config"]["resume_field"] == "resume_from_waypoint"
    conn._missions[tid]["breakpoint_at"] = time.time() - 7200
    assert conn.breakpoint_status(task_id=tid)["breakpoints"][0]["stale"] is True
    assert conn.breakpoint_status(task_id="missing")["breakpoints"] == []
    assert conn.breakpoint_status(drone_sn="OTHER")["breakpoints"] == []
    assert len(conn.breakpoint_status(drone_sn=SN)["breakpoints"]) == 1


def test_api_breakpoint_query_and_resume_from(client, mock_connector):
    r = client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN, "waypoints": WPS,
    })
    tid = r.json()["task_id"]
    client.post("/api/v1/dji/mission/control", json={
        "task_id": tid, "action": "execute",
    })
    mock_connector.mock_tick(1.0)
    client.post("/api/v1/dji/mission/control", json={
        "task_id": tid, "action": "pause",
    })
    bp = client.get("/api/v1/dji/mission/breakpoint", params={"task_id": tid})
    assert bp.status_code == 200
    assert bp.json()["breakpoints"][0]["breakpoint"] == 1

    r2 = client.post("/api/v1/dji/mission/resume-from", json={
        "task_id": tid, "waypoint_index": 0,
    })
    assert r2.status_code == 200
    assert r2.json()["resume_from"] == 0
    st = client.get("/api/v1/dji/mission/status", params={"task_id": tid})
    assert st.json()["missions"][0]["resume_from"] == 0
