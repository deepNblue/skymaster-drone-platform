"""T7.6 — UOM /reports.csv export tests."""
from __future__ import annotations

import io
import csv
from datetime import datetime, timedelta, timezone

import pytest


async def _seed_report(client, operator_id: str, pilot="LI"):
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/uom/reports",
        json={
            "operator_id": operator_id,
            "pilot_name": pilot,
            "aircraft_reg": f"N-{operator_id[:4].upper()}",
            "purpose": "aerial photography, 光电勘测",  # commas + CJK — CSV torture test
            "area_polygon": [[104.0, 30.6], [104.02, 30.6], [104.02, 30.62]],
            "max_alt_m": 120,
            "start_ts": (now + timedelta(hours=1)).timestamp(),
            "end_ts": (now + timedelta(hours=3)).timestamp(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _parse_csv(body: bytes) -> tuple[list[str], list[list[str]]]:
    text = body.decode("utf-8-sig")   # strip BOM
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


@pytest.mark.asyncio
async def test_reports_csv_basic(client):
    op = f"op-t76-{datetime.now().timestamp():.0f}"
    rid = await _seed_report(client, op)

    r = await client.get(f"/api/v1/uom/reports.csv?operator_id={op}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="uom_reports.csv"' in r.headers["content-disposition"]
    assert r.headers.get("x-row-count") == "1"

    # BOM present → Excel-friendly
    assert r.content[:3] == b"\xef\xbb\xbf"

    header, data = _parse_csv(r.content)
    assert "id" in header
    assert "operator_id" in header
    assert "purpose" in header
    assert "area_polygon" in header
    assert len(data) == 1
    row = dict(zip(header, data[0]))
    assert row["id"] == rid
    assert row["operator_id"] == op
    # commas + Chinese preserved via CSV quoting
    assert "光电勘测" in row["purpose"]
    assert "aerial photography" in row["purpose"]
    # polygon serialized as JSON string
    assert row["area_polygon"].startswith("[[")


@pytest.mark.asyncio
async def test_reports_csv_operator_scoping(client):
    op_a = f"op-t76-a-{datetime.now().timestamp():.0f}"
    op_b = f"op-t76-b-{datetime.now().timestamp():.0f}"
    await _seed_report(client, op_a, pilot="A")
    await _seed_report(client, op_a, pilot="A2")
    await _seed_report(client, op_b, pilot="B")

    r = await client.get(f"/api/v1/uom/reports.csv?operator_id={op_a}")
    assert r.status_code == 200
    assert r.headers["x-row-count"] == "2"
    _, data = _parse_csv(r.content)
    assert len(data) == 2

    r = await client.get(f"/api/v1/uom/reports.csv?operator_id={op_b}")
    assert r.headers["x-row-count"] == "1"


@pytest.mark.asyncio
async def test_reports_csv_status_filter(client):
    op = f"op-t76-status-{datetime.now().timestamp():.0f}"
    rid = await _seed_report(client, op)

    # Draft — pending review → filter status=pending returns it
    r = await client.get(
        f"/api/v1/uom/reports.csv?operator_id={op}&status=pending"
    )
    assert r.status_code == 200
    assert r.headers["x-row-count"] == "1"

    # Invalid status → 400 (guards against typo abuse)
    r = await client.get(
        f"/api/v1/uom/reports.csv?operator_id={op}&status=bogus"
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reports_csv_empty_operator(client):
    r = await client.get("/api/v1/uom/reports.csv?operator_id=nonexistent-op")
    assert r.status_code == 200
    assert r.headers["x-row-count"] == "0"
    header, data = _parse_csv(r.content)
    assert data == []
    # Header still present even when zero rows
    assert "id" in header
