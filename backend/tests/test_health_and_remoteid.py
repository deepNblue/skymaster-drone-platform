"""Tests for /livez /readyz + Remote ID mock."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_livez_always_ok(client):
    r = await client.get("/api/v1/livez")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readyz_returns_status(client):
    """readyz returns 200 iff both DB+Redis alive, else 503.

    In CI/tests we don't necessarily have real Postgres, so we accept
    either shape but assert the response structure is well-formed.
    """
    r = await client.get("/api/v1/readyz")
    assert r.status_code in (200, 503)
    body = r.json()
    if r.status_code == 200:
        assert body["status"] == "ready"
    else:
        # HTTPException wraps detail
        detail = body.get("detail", body)
        assert detail["status"] == "not_ready"
        # At least one of db/redis must have failed
        assert "error" in detail["db"] or "error" in detail["redis"]


@pytest.mark.asyncio
async def test_remoteid_broadcast_and_query(client):
    # Clear residual first (admin-role hook, auth_optional lets us in).
    from app.services.remoteid import clear
    clear()

    r = await client.post(
        "/api/v1/remoteid/broadcast",
        json={
            "uas_id": "UAS-TEST-01",
            "uas_id_type": 1,
            "lat": 22.55, "lng": 113.95, "alt_m": 100,
            "track_deg": 45, "speed_ms": 8,
            "operator_id": "org-e2e",
            "status": "airborne",
        },
    )
    assert r.status_code == 201, r.text

    # Query all
    r = await client.get("/api/v1/remoteid/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert any(m["uas_id"] == "UAS-TEST-01" for m in msgs)

    # Query one
    r = await client.get("/api/v1/remoteid/messages/UAS-TEST-01")
    assert r.status_code == 200
    body = r.json()
    assert body["uas_id"] == "UAS-TEST-01"
    assert body["lat"] == 22.55

    # 404 on unknown
    r = await client.get("/api/v1/remoteid/messages/UAS-DOES-NOT-EXIST")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_remoteid_missing_uas_returns_empty(client):
    from app.services.remoteid import clear
    clear()

    r = await client.get("/api/v1/remoteid/messages")
    assert r.status_code == 200
    assert r.json() == {"messages": []}
