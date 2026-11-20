"""Flight task state machine tests (config-driven, no hardcoded parameters)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.dji_cloud_connector import DJICloudConnector, METHOD_TASK_PROGRESS

SN = "MOCKM300-01"


@pytest.fixture
def conn():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    return c


def feed(conn, data, method=METHOD_TASK_PROGRESS):
    msg = SimpleNamespace(
        topic="thing/product/TESTDOCK/services",
        payload=json.dumps({"method": method, "data": data}).encode("utf-8"),
    )
    conn._on_mqtt_message(None, None, msg)


def test_routes_and_config_loaded(conn):
    routes = conn.mission_routes()
    assert len(routes) >= 3
    assert routes[0]["id"] == "nanning-12309-perimeter"
    assert conn._mission_cfg()["terminal_states"] == [
        "success", "failed", "cancelled"]


def test_create_mission_normalizes_waypoints(conn):
    tid = conn.create_mission(SN, [{"lat": 22.81, "lng": 108.31}])
    assert tid
    slot = conn._missions[tid]
    assert slot["waypoints"] == [{"lat": 22.81, "lng": 108.31, "alt": 80.0}]
    assert slot["state"] == "prepared"
    assert conn._mission_by_sn[SN] == tid


def test_invalid_waypoints_rejected(conn):
    assert conn.create_mission(SN, [{"lat": "bad", "lng": 108.31}]) is None
    assert conn._missions == {}


def test_mock_mission_completes(conn):
    tid = conn.create_mission(SN, [
        {"lat": 22.81, "lng": 108.31},
        {"lat": 22.82, "lng": 108.32},
    ])
    assert conn.flighttask_execute(tid, "f-1")
    assert conn._missions[tid]["state"] == "running"
    conn.mock_tick(1.0)
    assert conn._missions[tid]["progress"] == 50.0
    conn.mock_tick(1.0)
    assert conn._missions[tid]["state"] == "success"
    assert conn._missions[tid]["progress"] == 100.0


def test_pause_resume_cancel(conn):
    tid = conn.create_mission(SN, [
        {"lat": 22.81, "lng": 108.31},
        {"lat": 22.82, "lng": 108.32},
    ])
    conn.flighttask_execute(tid, "f-1")
    conn.flighttask_pause(tid)
    assert conn._missions[tid]["state"] == "paused"
    conn.mock_tick(1.0)
    assert conn._missions[tid]["idx"] == 0  # paused missions do not advance
    conn.flighttask_resume(tid)
    assert conn._missions[tid]["state"] == "running"
    conn.flighttask_cancel(tid)
    assert conn._missions[tid]["state"] == "cancelled"


def test_progress_reply_updates_state(conn):
    tid = conn.create_mission(SN, [{"lat": 22.81, "lng": 108.31}])
    feed(conn, {
        "task_id": tid, "state": "in_progress",
        "progress": 35, "message": "climbing",
    })
    slot = conn._missions[tid]
    assert slot["state"] == "running"
    assert slot["progress"] == 35
    assert slot["message"] == "climbing"


def test_progress_reply_normalizes_ratio_and_failure(conn):
    tid = conn.create_mission(SN, [{"lat": 22.81, "lng": 108.31}])
    feed(conn, {"task_id": tid, "progress": 0.7})
    assert conn._missions[tid]["progress"] == 70.0
    feed(conn, {
        "task_id": tid, "progress": 90,
        "result": -1, "message": "gps lost",
    })
    slot = conn._missions[tid]
    assert slot["state"] == "failed"
    assert slot["progress"] == 90
    assert slot["message"] == "gps lost"


def test_progress_reply_by_sn_when_task_id_absent(conn):
    tid = conn.create_mission(SN, [{"lat": 22.81, "lng": 108.31}])
    feed(conn, {"drone_sn": SN, "status": "completed", "progress": 100})
    assert conn._missions[tid]["state"] == "success"


def test_unknown_task_progress_ignored(conn):
    feed(conn, {"task_id": "does-not-exist", "progress": 99})
    assert conn._missions == {}


def test_multi_aircraft_isolation():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=2)
    c.connect()
    sn1, sn2 = "MOCKM300-01", "MOCKM300-02"
    wp = [{"lat": 22.81, "lng": 108.31}, {"lat": 22.82, "lng": 108.32}]
    t1 = c.create_mission(sn1, wp)
    t2 = c.create_mission(sn2, wp)
    c.flighttask_execute(t1, "f-1")
    c.flighttask_execute(t2, "f-2")
    c.mock_tick(1.0)
    assert c._missions[t1]["idx"] == 1
    assert c._missions[t2]["idx"] == 1
    c.flighttask_pause(t1)
    c.mock_tick(1.0)
    assert c._missions[t1]["idx"] == 1
    assert c._missions[t2]["idx"] == 2


def test_status_filters_and_sorted(conn):
    t1 = conn.create_mission(SN, [{"lat": 22.81, "lng": 108.31}])
    conn.create_mission("MOCKM300-02", [{"lat": 22.82, "lng": 108.32}])
    assert len(conn.mission_status(drone_sn=SN)["missions"]) == 1
    assert conn.mission_status(task_id=t1)["missions"][0]["task_id"] == t1
    assert len(conn.mission_status()["missions"]) == 2
