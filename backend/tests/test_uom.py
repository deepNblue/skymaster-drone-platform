"""Tests for UOM mock adapter and REST endpoints (v2.0 Module ①)."""
from __future__ import annotations

import time
import pytest


def _future_window(offset: float = 60, dur: float = 3600):
    start = time.time() + offset
    return start, start + dur


@pytest.mark.asyncio
async def test_uom_full_flow_via_api(client):
    ac = client
    s, e = _future_window()
    r = await ac.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-1",
            "pilot_name": "王小飞",
            "aircraft_reg": "UAS-2025-000123",
            "purpose": "航拍",
            "area_polygon": [
                [116.3, 39.9], [116.5, 39.9], [116.5, 40.0], [116.3, 40.0],
            ],
            "max_alt_m": 120,
            "start_ts": s,
            "end_ts": e,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    rid = body["id"]
    assert body["status"] == "pending"

    r = await ac.post(
        f"/api/v1/uom/reports/{rid}/approve",
        json={"reviewer": "test-supervisor"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["approval_code"].startswith("UOM-")

    r = await ac.get("/api/v1/uom/reports?status=approved")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = await ac.post(
        "/api/v1/uom/check",
        json={
            "mission_area": [
                [116.35, 39.92], [116.45, 39.92], [116.45, 39.98],
            ],
            "at_ts": s + 100,
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True, r.json()

    r = await ac.post(
        "/api/v1/uom/check",
        json={
            "mission_area": [
                [116.35, 39.92], [116.45, 39.92], [116.45, 39.98],
            ],
            "at_ts": e + 100,
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_uom_reject(client):
    ac = client
    s, e = _future_window()
    r = await ac.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-2",
            "pilot_name": "李二飞",
            "aircraft_reg": "UAS-2025-000124",
            "purpose": "巡检",
            "area_polygon": [
                [104.05, 30.55], [104.10, 30.55], [104.10, 30.60],
            ],
            "max_alt_m": 90,
            "start_ts": s,
            "end_ts": e,
        },
    )
    rid = r.json()["id"]
    r = await ac.post(
        f"/api/v1/uom/reports/{rid}/reject",
        json={"reason": "空域临时管制", "reviewer": "test-atc"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["reject_reason"] == "空域临时管制"

    r = await ac.post(
        f"/api/v1/uom/reports/{rid}/approve", json={"reviewer": "x"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_uom_validation(client):
    ac = client
    s = time.time() + 60
    r = await ac.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-3",
            "pilot_name": "p",
            "aircraft_reg": "x",
            "purpose": "y",
            "area_polygon": [[116, 39], [116.5, 39]],
            "max_alt_m": 100,
            "start_ts": s,
            "end_ts": s + 3600,
        },
    )
    assert r.status_code in (400, 422)

    r = await ac.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": "org-3",
            "pilot_name": "p",
            "aircraft_reg": "x",
            "purpose": "y",
            "area_polygon": [[116, 39], [116.5, 39], [116.5, 39.5]],
            "max_alt_m": 100,
            "start_ts": s + 3600,
            "end_ts": s,
        },
    )
    assert r.status_code == 400

