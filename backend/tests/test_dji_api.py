"""Tests for the DJI control HTTP façade."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.dji_cloud_connector import DJICloudConnector


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)
    return TestClient(app)


@pytest.fixture
def mock_connector():
    c = DJICloudConnector(
        gateway_sn="TESTDOCK", mode="mock", mock_drones=1,
        drone_id_map={"MOCKM300-01": "4b01c55d-1038-48ee-a3a9-93c453cac89b"},
    )
    c.connect()
    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = c
    yield c
    if old is None and hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    else:
        app.state.dji_connector = old


def test_status_without_connector_returns_503(client):
    if hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    r = client.get("/api/v1/dji/status")
    assert r.status_code == 503
    assert "DJI connector not mounted" in r.json()["detail"]


def test_status_reports_connector(client, mock_connector):
    r = client.get("/api/v1/dji/status")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    assert d["mode"] == "mock"
    assert d["gateway_sn"] == "TESTDOCK"
    assert "MOCKM300-01" in d["aircraft"]


def test_drc_endpoint_sends_and_records(client, mock_connector):
    r = client.post("/api/v1/dji/drc", json={
        "drone_sn": "MOCKM300-01",
        "throttle": 0.6, "yaw": -0.3, "pitch": 0.1, "roll": 0.2,
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert mock_connector.last_drc["MOCKM300-01"]["throttle"] == 0.6
    assert mock_connector._mock_state["MOCKM300-01"] == "DRC"
    # status reflects the command
    s = client.get("/api/v1/dji/status").json()
    assert s["last_drc"]["MOCKM300-01"]["yaw"] == -0.3


def test_drc_rejects_out_of_range(client, mock_connector):
    r = client.post("/api/v1/dji/drc", json={
        "drone_sn": "MOCKM300-01", "throttle": 1.5,
    })
    assert r.status_code == 422


def test_action_return_home_and_hover(client, mock_connector):
    r = client.post("/api/v1/dji/action", json={
        "action": "return_home", "drone_sn": "MOCKM300-01",
    })
    assert r.status_code == 200
    assert mock_connector._mock_state["MOCKM300-01"] == "RETURN_TO_HOME"

    r = client.post("/api/v1/dji/action", json={
        "action": "hover", "drone_sn": "MOCKM300-01",
    })
    assert r.status_code == 200
    assert mock_connector._mock_state["MOCKM300-01"] == "DRC"


def test_action_live_start_requires_url(client, mock_connector):
    r = client.post("/api/v1/dji/action", json={
        "action": "live_start", "drone_sn": "MOCKM300-01",
    })
    assert r.status_code == 422
    assert "rtmp_url" in r.json()["detail"]


def test_action_unknown(client, mock_connector):
    r = client.post("/api/v1/dji/action", json={
        "action": "teleport", "drone_sn": "MOCKM300-01",
    })
    assert r.status_code == 422
