"""Audit-log middleware tests — v2.0 compliance track.

Uses the in-memory audit sink so we don't need a real Postgres.
"""
from __future__ import annotations

import os
import time
import pytest


@pytest.fixture(autouse=True)
def _enable_memory_sink(monkeypatch, client):
    """Force the app to install an InMemoryAuditSink for these tests.

    Note: env vars alone aren't enough because the `client` fixture
    imports app.main *once* per process — by the time we get here,
    the middleware may already be initialized without a sink.  So we
    also directly set app.state.audit_sink and install the middleware
    if it isn't already present.
    """
    monkeypatch.setenv("AUDIT_MEMORY_SINK", "true")
    monkeypatch.setenv("ENABLE_AUDIT_MIDDLEWARE", "true")

    from app.services.audit_middleware import (
        AuditMiddleware,
        InMemoryAuditSink,
    )

    app = client._transport.app  # type: ignore[attr-defined]

    # Ensure a sink exists on state
    if not getattr(app.state, "audit_sink", None):
        app.state.audit_sink = InMemoryAuditSink()

    # Ensure AuditMiddleware is in the stack (idempotent per test run)
    from starlette.middleware.base import BaseHTTPMiddleware
    stack = getattr(app, "user_middleware", [])
    has_audit = any(m.cls is AuditMiddleware for m in stack)
    if not has_audit:
        app.add_middleware(AuditMiddleware)
        # Force re-build of the middleware stack so the added
        # middleware actually takes effect.
        app.middleware_stack = app.build_middleware_stack()


@pytest.mark.asyncio
async def test_audit_captures_mutating_calls(client):
    """POST /geofence/check is mutating → should be audited.
    GET /geofence/zones is read-only → should NOT be audited.
    """
    sink = client._transport.app.state.audit_sink  # type: ignore[attr-defined]
    sink.events.clear()

    # A GET — should not create an audit entry.
    r = await client.get("/api/v1/geofence/zones")
    assert r.status_code == 200
    assert not any(e["action"].startswith("GET ") for e in sink.events)

    # A POST — should be audited.
    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [{"lat": 22.5, "lng": 113.9, "alt": 100}]},
    )
    assert r.status_code == 200
    posts = [e for e in sink.events if e["action"].startswith("POST ")]
    assert len(posts) == 1
    assert "/geofence/check" in posts[0]["action"]
    assert posts[0]["diff"]["status_code"] == 200
    assert posts[0]["ts"] > 0


@pytest.mark.asyncio
async def test_audit_captures_uom_flow(client):
    sink = client._transport.app.state.audit_sink  # type: ignore[attr-defined]
    sink.events.clear()

    s = time.time() + 60
    r = await client.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-audit",
            "pilot_name": "审计测试",
            "aircraft_reg": "UAS-audit",
            "purpose": "test",
            "area_polygon": [[116, 39], [116.5, 39], [116.5, 39.5], [116, 39.5]],
            "max_alt_m": 100,
            "start_ts": s,
            "end_ts": s + 3600,
        },
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    r = await client.post(
        f"/api/v1/uom/reports/{rid}/approve", json={"reviewer": "audit-test"}
    )
    assert r.status_code == 200

    submit_events = [e for e in sink.events if "/uom/reports" in e["action"] and "approve" not in e["action"] and "reject" not in e["action"]]
    approve_events = [e for e in sink.events if "approve" in e["action"]]
    assert len(submit_events) >= 1
    assert len(approve_events) >= 1
    assert approve_events[0]["diff"]["status_code"] == 200
