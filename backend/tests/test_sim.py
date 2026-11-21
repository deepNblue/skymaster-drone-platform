"""Tests for the sim control router (MM — mission dispatch)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


class _MockDroneHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    state = {"mode": "circle", "armed": True, "mission_progress": "0/0"}

    def log_message(self, *a, **k):  # noqa: ARG002
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/state":
            self._json(200, self.state)
        else:
            self._json(404, {})

    def do_POST(self):  # noqa: N802
        if self.path != "/command":
            self._json(404, {})
            return
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _MockDroneHandler.received.append(body)
        if body.get("type") == "mission":
            self.state["mission_progress"] = f"0/{len(body.get('waypoints', []))}"
        if body.get("type") in ("goto", "mission", "rtl", "hover", "circle", "line"):
            self.state["mode"] = body["type"]
        self._json(200, {"ok": True, "mode": self.state["mode"]})


@pytest.fixture
def mock_drone():
    """Spin up a mock FakeDrone HTTP command server on port 15901."""
    _MockDroneHandler.received.clear()
    _MockDroneHandler.state = {"mode": "circle", "armed": True, "mission_progress": "0/0"}
    server = HTTPServer(("127.0.0.1", 15901), _MockDroneHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield
    server.shutdown()
    server.server_close()


@pytest.fixture
def client(monkeypatch, mock_drone):
    monkeypatch.setenv("SIM_DRONES", "99:15901")
    # Force re-parse
    from app.api.v1 import sim as sim_router
    sim_router._REGISTRY = sim_router._default_registry()  # type: ignore
    return TestClient(app)


def test_list_sim_drones(client):
    r = client.get("/api/v1/sim/drones")
    assert r.status_code == 200
    assert r.json()["drones"] == [{"sysid": 99, "command_port": 15901}]


def test_sim_state(client):
    r = client.get("/api/v1/sim/drones/99/state")
    assert r.status_code == 200
    assert r.json()["mode"] == "circle"


def test_sim_goto(client):
    r = client.post(
        "/api/v1/sim/drones/99/goto",
        json={"lat": 39.9, "lng": 116.4, "alt": 100},
    )
    assert r.status_code == 200
    assert _MockDroneHandler.received[-1] == {
        "type": "goto", "lat": 39.9, "lng": 116.4, "alt": 100,
    }


def test_sim_mission(client):
    # Existing test relies on no UOM/geofence — skip compliance to preserve.
    wps = [{"lat": 39.9, "lng": 116.4, "alt": 80},
           {"lat": 39.91, "lng": 116.41, "alt": 100}]
    r = client.post(
        "/api/v1/sim/drones/99/mission",
        json={"waypoints": wps, "skip_compliance": True},
    )
    assert r.status_code == 200
    assert _MockDroneHandler.received[-1]["type"] == "mission"
    assert len(_MockDroneHandler.received[-1]["waypoints"]) == 2


def test_sim_rtl(client):
    r = client.post("/api/v1/sim/drones/99/rtl")
    assert r.status_code == 200
    assert _MockDroneHandler.received[-1] == {"type": "rtl"}


def test_sim_mode(client):
    r = client.post("/api/v1/sim/drones/99/mode", json={"mode": "hover"})
    assert r.status_code == 200
    r = client.post("/api/v1/sim/drones/99/mode", json={"mode": "invalid"})
    assert r.status_code == 400


def test_sim_unknown_sysid(client):
    r = client.get("/api/v1/sim/drones/77/state")
    assert r.status_code == 503 or r.status_code == 404
