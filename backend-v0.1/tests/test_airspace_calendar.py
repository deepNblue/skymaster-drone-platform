"""E2.5b · Airspace calendar tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"cal+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


# Chengdu-ish patch (small square around 30.5N, 103.0E, ~0.05deg).
POLY_A = [[103.00, 30.50], [103.05, 30.50], [103.05, 30.55], [103.00, 30.55]]
# Overlapping bbox.
POLY_OVERLAP = [[103.02, 30.51], [103.07, 30.51], [103.07, 30.57]]
# Disjoint (Chongqing-ish).
POLY_FAR = [[106.50, 29.50], [106.55, 29.50], [106.55, 29.55]]


async def test_create_and_list_entry(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local",
            "title": "test-slot",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "min_alt_m": 30, "max_alt_m": 120,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    eid = body["id"]
    assert body["bbox_min_lon"] == 103.0
    assert body["bbox_max_lat"] == 30.55

    r = await client.get("/api/v1/airspace-calendar", headers=_h(tok))
    assert r.status_code == 200
    assert any(e["id"] == eid for e in r.json())


async def test_source_enum_enforced(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "bad-src",
            "title": "x",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 400
    assert "source" in r.text.lower()


async def test_end_before_start_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local",
            "title": "x",
            "geo_polygon": POLY_A,
            "start_ts": (now + timedelta(hours=2)).isoformat(),
            "end_ts": now.isoformat(),
        },
    )
    assert r.status_code == 400


async def test_check_conflicts_time_bbox_overlap(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Existing UOM slot 09:00-11:00 over POLY_A.
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "uom", "title": "uom-slot",
            "external_ref": "UOM-2026-0001",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "min_alt_m": 20, "max_alt_m": 200,
        },
    )
    assert r.status_code == 201

    # Probe: overlapping polygon, overlapping time — should conflict.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_OVERLAP,
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert r.json()["conflicts"][0]["source"] == "uom"

    # Probe: same polygon but time window fully after.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_OVERLAP,
            "start_ts": (now + timedelta(hours=3)).isoformat(),
            "end_ts": (now + timedelta(hours=4)).isoformat(),
        },
    )
    assert r.json()["count"] == 0

    # Probe: same time but disjoint polygon.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_FAR,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert r.json()["count"] == 0


async def test_check_conflicts_altitude_band(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Existing entry at 100-200 m.
    await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local", "title": "high",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "min_alt_m": 100, "max_alt_m": 200,
        },
    )

    # Probe at 300-400 m same polygon+time — should NOT conflict.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
            "min_alt_m": 300, "max_alt_m": 400,
        },
    )
    assert r.json()["count"] == 0

    # Probe at 150-350 m — bands overlap, should conflict.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
            "min_alt_m": 150, "max_alt_m": 350,
        },
    )
    assert r.json()["count"] == 1


async def test_exclude_ids_skip_self(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local", "title": "own",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    eid = r.json()["id"]

    # Probe self with exclude_ids -> 0 conflicts.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "exclude_ids": [eid],
        },
    )
    assert r.json()["count"] == 0

    # Same probe without exclude -> 1 conflict.
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert r.json()["count"] == 1


async def test_cross_org_isolation(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok_a),
        json={
            "source": "local", "title": "a-slot",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok_b),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert r.json()["count"] == 0


async def test_delete_hides_from_conflicts(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local", "title": "gone",
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    eid = r.json()["id"]
    r = await client.delete(
        f"/api/v1/airspace-calendar/{eid}", headers=_h(tok),
    )
    assert r.status_code == 204

    r = await client.post(
        "/api/v1/airspace-calendar/check-conflicts", headers=_h(tok),
        json={
            "geo_polygon": POLY_A,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert r.json()["count"] == 0


async def test_empty_polygon_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "local", "title": "x",
            "geo_polygon": [],
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 400
