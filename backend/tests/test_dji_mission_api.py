"""HTTP façade tests for the DJI flight task endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.dji_cloud_connector import DJICloudConnector

SN = "MOCKM300-01"


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


def test_routes_endpoint(client, mock_connector):
    r = client.get("/api/v1/dji/mission/routes")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["routes"]]
    assert "nanning-12309-perimeter" in ids


def test_prepare_from_route_and_status(client, mock_connector):
    r = client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN, "route_id": "nanning-12309-perimeter",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["waypoint_count"] == 5
    tid = d["task_id"]

    st = client.get("/api/v1/dji/mission/status",
                    params={"task_id": tid}).json()
    assert st["missions"][0]["state"] == "prepared"
    assert st["missions"][0]["drone_sn"] == SN


def test_prepare_from_explicit_waypoints(client, mock_connector):
    r = client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN,
        "waypoints": [{"lat": 22.81, "lng": 108.31, "alt": 95}],
    })
    assert r.status_code == 200
    st = client.get("/api/v1/dji/mission/status").json()["missions"][0]
    assert st["waypoints"][0]["alt"] == 95.0


def test_full_control_flow(client, mock_connector):
    tid = client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN,
        "waypoints": [
            {"lat": 22.81, "lng": 108.31},
            {"lat": 22.82, "lng": 108.32},
        ],
    }).json()["task_id"]

    def state():
        return client.get("/api/v1/dji/mission/status",
                          params={"task_id": tid}).json()["missions"][0]["state"]

    for action, expected in [
        ("execute", "running"),
        ("pause", "paused"),
        ("resume", "running"),
        ("cancel", "cancelled"),
    ]:
        r = client.post("/api/v1/dji/mission/control",
                        json={"task_id": tid, "action": action})
        assert r.status_code == 200
        assert r.json()["action"] == action
        assert state() == expected


def test_prepare_validation(client, mock_connector):
    assert client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN, "route_id": "nope",
    }).status_code == 404
    assert client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN,
    }).status_code == 422
    assert client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN, "waypoints": [{"lat": 22.81}],
    }).status_code == 503


def test_unknown_control_action(client, mock_connector):
    r = client.post("/api/v1/dji/mission/control", json={
        "task_id": "t-1", "action": "teleport",
    })
    assert r.status_code == 422


def test_503_without_connector(client):
    if hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    assert client.get("/api/v1/dji/mission/status").status_code == 503
    assert client.get("/api/v1/dji/mission/routes").status_code == 503
