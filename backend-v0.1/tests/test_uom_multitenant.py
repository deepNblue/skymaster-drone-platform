"""Multi-tenant UOM scoping tests — v1.0 org_id isolation."""
from __future__ import annotations

import time
import pytest


@pytest.mark.asyncio
async def test_uom_list_no_scope_returns_all(client):
    """Anonymous / no-org user sees everything (demo mode)."""
    # Submit two reports under different operators.
    now = time.time()
    for op in ("org-tenant-A", "org-tenant-B"):
        r = await client.post(
            "/api/v1/uom/reports",
            json={
                "operator_id": op,
                "pilot_name": f"pilot-{op}",
                "aircraft_reg": f"UAS-{op}",
                "purpose": "test",
                "area_polygon": [
                    [113.90, 22.50], [114.00, 22.50],
                    [114.00, 22.60], [113.90, 22.60],
                ],
                "max_alt_m": 100,
                "start_ts": now,
                "end_ts": now + 3600,
            },
        )
        assert r.status_code == 201

    r = await client.get("/api/v1/uom/reports")
    assert r.status_code == 200
    body = r.json()
    operators = {rpt["operator_id"] for rpt in body["reports"]}
    assert "org-tenant-A" in operators
    assert "org-tenant-B" in operators


@pytest.mark.asyncio
async def test_uom_list_filtered_by_operator_id(client):
    now = time.time()
    for op in ("org-scope-X", "org-scope-Y"):
        await client.post(
            "/api/v1/uom/reports",
            json={
                "operator_id": op,
                "pilot_name": "p",
                "aircraft_reg": "UAS",
                "purpose": "test",
                "area_polygon": [
                    [113.90, 22.50], [114.00, 22.50],
                    [114.00, 22.60], [113.90, 22.60],
                ],
                "max_alt_m": 100,
                "start_ts": now,
                "end_ts": now + 3600,
            },
        )
    r = await client.get("/api/v1/uom/reports?operator_id=org-scope-X")
    assert r.status_code == 200
    body = r.json()
    for rpt in body["reports"]:
        assert rpt["operator_id"] == "org-scope-X"
    assert body["scoped_by"] == "org-scope-X"
