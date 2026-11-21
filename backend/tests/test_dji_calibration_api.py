"""HTTP façade tests for the DJI calibration endpoints."""
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
def mock_connector(tmp_path):
    c = DJICloudConnector(
        gateway_sn="TESTDOCK", mode="mock", mock_drones=1,
        drone_id_map={SN: "4b01c55d-1038-48ee-a3a9-93c453cac89b"},
        rc_calibration_path=str(tmp_path / "rc.json"),
    )
    c.connect()
    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = c
    yield c
    if old is None and hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    else:
        app.state.dji_connector = old


def test_status_returns_items_and_config(client, mock_connector):
    r = client.get("/api/v1/dji/calibration/status", params={"drone_sn": SN})
    assert r.status_code == 200
    d = r.json()
    keys = [i["key"] for i in d["items"]]
    assert keys == ["compass", "imu", "gimbal", "vision", "rc"]
    assert d["config"]["rc_calibration"]["steps"][0]["key"] == "throttle_max"
    assert d["sensors"][SN] == {}


def test_start_and_cancel_sensor_calibration(client, mock_connector):
    r = client.post("/api/v1/dji/calibration/start",
                    json={"drone_sn": SN, "item": "compass"})
    assert r.status_code == 200
    st = client.get("/api/v1/dji/calibration/status",
                    params={"drone_sn": SN}).json()["sensors"][SN]["compass"]
    assert st["state"] == "running"

    r = client.post("/api/v1/dji/calibration/cancel",
                    json={"drone_sn": SN, "item": "compass"})
    assert r.status_code == 200
    st = client.get("/api/v1/dji/calibration/status",
                    params={"drone_sn": SN}).json()["sensors"][SN]["compass"]
    assert st["state"] == "cancelled"


def test_start_unknown_item_returns_422(client, mock_connector):
    r = client.post("/api/v1/dji/calibration/start",
                    json={"drone_sn": SN, "item": "teleport"})
    assert r.status_code == 422
    assert "unknown calibration item" in r.json()["detail"]


def test_rc_endpoint_saves_and_reports(client, mock_connector):
    axes = {a: {"min": -1.0, "center": 0.0, "max": 1.0}
            for a in ("throttle", "yaw", "pitch", "roll")}
    r = client.post("/api/v1/dji/calibration/rc",
                    json={"drone_sn": SN, "axes": axes})
    assert r.status_code == 200
    assert r.json()["deadzone"] == 0.05

    d = client.get("/api/v1/dji/calibration/status",
                   params={"drone_sn": SN}).json()
    assert d["rc"][SN]["axes"]["yaw"]["max"] == 1.0
    assert d["sensors"][SN]["rc"]["state"] == "success"


def test_rc_endpoint_rejects_invalid_endpoints(client, mock_connector):
    axes = {a: {"min": -1.0, "center": 0.0, "max": 1.0}
            for a in ("throttle", "yaw", "pitch", "roll")}
    axes["pitch"] = {"min": 0.5, "center": 0.0, "max": 1.0}
    r = client.post("/api/v1/dji/calibration/rc",
                    json={"drone_sn": SN, "axes": axes})
    assert r.status_code == 422
    assert "pitch" in r.json()["detail"]


def test_cancel_without_active_calibration_returns_404(client, mock_connector):
    r = client.post("/api/v1/dji/calibration/cancel",
                    json={"drone_sn": SN, "item": "vision"})
    assert r.status_code == 404


def test_calibration_status_without_connector_returns_503(client):
    if hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    r = client.get("/api/v1/dji/calibration/status")
    assert r.status_code == 503
