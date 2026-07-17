"""Metrics endpoint tests — v1.0 monitoring track."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format(client):
    # Trigger some requests to populate counters.
    await client.get("/api/v1/health")
    await client.get("/api/v1/geofence/zones")

    r = await client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    # Sanity: has our custom metrics.
    assert "skymaster_http_requests_total" in body
    assert "skymaster_http_request_duration_seconds" in body
    assert "skymaster_missions_dispatched_total" in body
    assert "skymaster_geofence_blocks_total" in body
    assert "skymaster_uom_reports_total" in body
    # And a HELP/TYPE line pattern:
    assert "# HELP skymaster_http_requests_total" in body
    assert "# TYPE skymaster_http_requests_total counter" in body


@pytest.mark.asyncio
async def test_metrics_records_geofence_block(client):
    # Send a mission into 天安门 no-fly (need mock drone port).
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading, json, os
    os.environ["SIM_DRONES"] = "77:15977"
    from app.api.v1 import sim as sim_router
    sim_router._REGISTRY = sim_router._default_registry()  # type: ignore

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **k): pass
        def do_POST(self):  # noqa: N802
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"ok":true}')
    srv = HTTPServer(("127.0.0.1", 15977), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = await client.post(
            "/api/v1/sim/drones/77/mission",
            json={"waypoints": [{"lat": 39.909, "lng": 116.397, "alt": 60}]},
        )
        assert r.status_code == 451

        r = await client.get("/api/v1/metrics")
        # Counter is process-global — just check the metric line exists with ≥1.
        found = False
        for line in r.text.splitlines():
            if line.startswith('skymaster_geofence_blocks_total{kind="no_fly"}'):
                val = float(line.rsplit(" ", 1)[1])
                if val >= 1:
                    found = True
                    break
        assert found, r.text
    finally:
        srv.shutdown()
        srv.server_close()
