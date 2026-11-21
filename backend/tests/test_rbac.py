"""RBAC / auth-mode tests — v1.0 permissions track."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_rbac_hierarchy_admin_gets_operator_access(monkeypatch):
    """Admin role must satisfy operator-gated dependencies."""
    from app.services.rbac import Role, has_at_least, is_admin, is_operator_or_above
    assert has_at_least("admin", Role.OPERATOR)
    assert has_at_least("admin", Role.VIEWER)
    assert has_at_least("operator", Role.OPERATOR)
    assert not has_at_least("operator", Role.ADMIN)
    assert not has_at_least("viewer", Role.OPERATOR)
    assert is_admin("admin")
    assert is_operator_or_above("operator")
    assert not is_operator_or_above("viewer")
    assert not has_at_least("garbage-role", Role.VIEWER)


@pytest.mark.asyncio
async def test_auth_optional_allows_dispatch_in_dev(client, monkeypatch):
    """With auth_optional=true (default in tests), sim/mission works
    without a Bearer token."""
    from app.config import settings
    assert settings.auth_optional is True  # sanity

    # Set up a mock drone at 15988
    import threading, json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    monkeypatch.setenv("SIM_DRONES", "88:15988")
    from app.api.v1 import sim as sim_router
    sim_router._REGISTRY = sim_router._default_registry()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **k): pass
        def do_POST(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"ok":true}')
    srv = HTTPServer(("127.0.0.1", 15988), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # No Authorization header — should succeed under auth_optional.
        r = await client.post(
            "/api/v1/sim/drones/88/mission",
            json={
                "waypoints": [{"lat": 22.55, "lng": 113.95, "alt": 80}],
                "skip_compliance": True,
            },
        )
        assert r.status_code == 200
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.asyncio
async def test_auth_required_when_disabled(client, monkeypatch):
    """When auth_optional=false, sim/mission requires a Bearer token."""
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", False)

    r = await client.post(
        "/api/v1/sim/drones/1/mission",
        json={
            "waypoints": [{"lat": 22.55, "lng": 113.95, "alt": 80}],
            "skip_compliance": True,
        },
    )
    assert r.status_code == 401
