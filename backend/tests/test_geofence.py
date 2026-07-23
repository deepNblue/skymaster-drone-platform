"""Tests for GeoFence engine + API — v2.0 compliance track."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_geofence_list_and_check_ok(client):
    r = await client.get("/api/v1/geofence/zones")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 4
    kinds = {z["kind"] for z in data["zones"]}
    assert "no_fly" in kinds and "height" in kinds

    # Waypoints far from any seed zone → ok
    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [
            {"lat": 22.5, "lng": 113.9, "alt": 100},
            {"lat": 22.6, "lng": 114.0, "alt": 100},
        ]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["violations"] == []


@pytest.mark.asyncio
async def test_geofence_no_fly_detection(client):
    # Waypoint inside 天安门 no-fly polygon
    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [{"lat": 39.909, "lng": 116.397, "alt": 60}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert any(v["kind"] == "no_fly" for v in body["violations"])


@pytest.mark.asyncio
async def test_geofence_height_cap(client):
    # Inside Beijing 120m cap zone; alt=200 → violation
    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [{"lat": 39.90, "lng": 116.35, "alt": 200}]},
    )
    body = r.json()
    assert body["ok"] is False
    # First hit will be no_fly (天安门 is inside 120m zone too) OR height
    kinds = [v["kind"] for v in body["violations"]]
    assert "height" in kinds

    # Same lat/lng but alt=80 → still no_fly if inside tiananmen,
    # otherwise fully ok. Pick a coord clearly inside height-only zone.
    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [{"lat": 39.85, "lng": 116.30, "alt": 200}]},
    )
    body = r.json()
    assert body["ok"] is False
    assert any(v["kind"] == "height" for v in body["violations"])

    r = await client.post(
        "/api/v1/geofence/check",
        json={"waypoints": [{"lat": 39.85, "lng": 116.30, "alt": 80}]},
    )
    assert r.json()["ok"] is True
