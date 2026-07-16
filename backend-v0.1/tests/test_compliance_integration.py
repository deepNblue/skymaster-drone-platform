"""Compliance-integration tests — GeoFence + UOM enforced on mission dispatch."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _OkHandler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):  # silence
        pass

    def do_POST(self):  # noqa: N802
        ln = int(self.headers.get("Content-Length", 0))
        self.rfile.read(ln)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "mode": "mission"}).encode())


@pytest.fixture
def _mock_fakedrone(monkeypatch):
    """Register a mock FakeDrone on 15901 and expose sysid=99."""
    monkeypatch.setenv("SIM_DRONES", "99:15901")
    from app.api.v1 import sim as sim_router

    sim_router._REGISTRY = sim_router._default_registry()  # type: ignore
    srv = HTTPServer(("127.0.0.1", 15901), _OkHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.asyncio
async def test_mission_blocked_by_no_fly_zone(client, _mock_fakedrone):
    r = await client.post(
        "/api/v1/sim/drones/99/mission",
        json={
            "waypoints": [
                {"lat": 39.909, "lng": 116.397, "alt": 60},
            ],
        },
    )
    assert r.status_code == 451, r.text
    assert r.json()["detail"]["code"] == "geofence_violation"


@pytest.mark.asyncio
async def test_mission_blocked_without_uom_report(client, _mock_fakedrone):
    r = await client.post(
        "/api/v1/sim/drones/99/mission",
        json={
            "waypoints": [
                {"lat": 22.55, "lng": 113.95, "alt": 80},
                {"lat": 22.56, "lng": 113.96, "alt": 80},
                {"lat": 22.57, "lng": 113.97, "alt": 80},
            ],
        },
    )
    assert r.status_code == 451, r.text
    assert r.json()["detail"]["code"] == "uom_not_ready"


@pytest.mark.asyncio
async def test_mission_passes_with_approved_uom(client, _mock_fakedrone):
    now = time.time()
    r = await client.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-e2e",
            "pilot_name": "e2e",
            "aircraft_reg": "UAS-e2e",
            "purpose": "test",
            "area_polygon": [
                [113.90, 22.50], [114.00, 22.50],
                [114.00, 22.60], [113.90, 22.60],
            ],
            "max_alt_m": 120,
            "start_ts": now,
            "end_ts": now + 3600,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await client.post(
        f"/api/v1/uom/reports/{rid}/approve", json={"reviewer": "e2e"}
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/sim/drones/99/mission",
        json={
            "waypoints": [
                {"lat": 22.55, "lng": 113.95, "alt": 80},
                {"lat": 22.56, "lng": 113.96, "alt": 80},
                {"lat": 22.57, "lng": 113.97, "alt": 80},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("compliance", {}).get("geofence", {}).get("ok") is True
    assert body.get("compliance", {}).get("uom", {}).get("ok") is True


@pytest.mark.asyncio
async def test_mission_skip_compliance(client, _mock_fakedrone):
    """skip_compliance=true bypasses both UOM & geofence."""
    r = await client.post(
        "/api/v1/sim/drones/99/mission",
        json={
            "waypoints": [
                {"lat": 39.909, "lng": 116.397, "alt": 60},
            ],
            "skip_compliance": True,
        },
    )
    assert r.status_code == 200, r.text
