"""E3.1 · Detection clustering tests — pure + REST."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.models.vision_copilot import VisionDetection
from app.services.auth import create_access_token, hash_password
from app.services.detection_cluster import (
    _haversine_m, cluster_detections, compute_label_stats,
)

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"dc+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _mk_dets(
    org_id: UUID, entries: list[dict],
) -> None:
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        for e in entries:
            s.add(VisionDetection(
                tenant_id=org_id,
                drone_id=e.get("drone_id"),
                label=e["label"],
                confidence=e.get("confidence", 0.9),
                lat=e.get("lat"),
                lng=e.get("lng"),
                created_at=e["created_at"],
            ))
        await s.commit()


# ============ Pure clustering ============

def test_haversine_zero_same_point() -> None:
    assert _haversine_m(30, 120, 30, 120) == 0


def test_haversine_reasonable_distance() -> None:
    # Chengdu ~ 1000m north
    d = _haversine_m(30.6595, 104.0658, 30.6685, 104.0658)
    assert 900 < d < 1100


def test_cluster_single_point() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    cs = cluster_detections([{
        "id": "1", "label": "person", "confidence": 0.9,
        "lat": 30.6, "lng": 104.0, "created_at": t0,
        "drone_id": "d1",
    }])
    assert len(cs) == 1
    assert cs[0]["member_count"] == 1
    assert cs[0]["drone_ids"] == ["d1"]


def test_cluster_merges_nearby_in_time() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": str(i), "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=i * 2),
         "drone_id": "d1"}
        for i in range(5)
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 1
    assert cs[0]["member_count"] == 5


def test_cluster_splits_on_time_gap() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "1", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0, "created_at": t0},
        {"id": "2", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=120)},  # >30s
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 2


def test_cluster_splits_on_spatial_gap() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "1", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0, "created_at": t0},
        {"id": "2", "label": "person", "confidence": 0.9,
         "lat": 30.7, "lng": 104.0,  # ~11km away
         "created_at": t0 + timedelta(seconds=5)},
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 2


def test_cluster_splits_on_different_label() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "1", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0, "created_at": t0},
        {"id": "2", "label": "vehicle", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=5)},
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 2


def test_cluster_centroid_runs_average() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "1", "label": "car", "confidence": 0.7,
         "lat": 30.60000, "lng": 104.0, "created_at": t0},
        {"id": "2", "label": "car", "confidence": 0.9,
         "lat": 30.60010, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=2)},
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 1
    # centroid mid ~ 30.60005
    assert abs(cs[0]["centroid_lat"] - 30.60005) < 1e-5
    assert cs[0]["peak_confidence"] == 0.9


def test_cluster_skips_missing_gps() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    cs = cluster_detections([
        {"id": "1", "label": "person", "confidence": 0.9,
         "lat": None, "lng": None, "created_at": t0},
    ])
    assert cs == []


def test_cluster_multi_drone_uniq_ids() -> None:
    t0 = datetime(2026, 7, 17, 3, 0, tzinfo=timezone.utc)
    rows = [
        {"id": "1", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0, "drone_id": "d1"},
        {"id": "2", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=1),
         "drone_id": "d1"},
        {"id": "3", "label": "person", "confidence": 0.9,
         "lat": 30.6, "lng": 104.0,
         "created_at": t0 + timedelta(seconds=2),
         "drone_id": "d2"},
    ]
    cs = cluster_detections(rows)
    assert len(cs) == 1
    assert set(cs[0]["drone_ids"]) == {"d1", "d2"}


def test_compute_label_stats() -> None:
    rows = [
        {"label": "person", "confidence": 0.9, "drone_id": "d1"},
        {"label": "person", "confidence": 0.85, "drone_id": "d1"},
        {"label": "person", "confidence": 0.7, "drone_id": "d2"},
        {"label": "vehicle", "confidence": 0.95, "drone_id": "d1"},
    ]
    stats = compute_label_stats(rows)
    assert stats[0]["label"] == "person"  # sorted by count desc
    assert stats[0]["count"] == 3
    assert stats[0]["distinct_drones"] == 2
    assert abs(stats[0]["avg_confidence"] - 0.8167) < 0.001
    assert stats[0]["peak_confidence"] == 0.9
    assert stats[1]["label"] == "vehicle"
    assert stats[1]["count"] == 1


# ============ REST integration ============

async def test_analytics_empty_scene(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/vision/analytics/clusters", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_detections"] == 0
    assert body["cluster_count"] == 0
    assert body["clusters"] == []
    assert body["by_label"] == []


async def test_analytics_with_detections(client) -> None:
    tok, _, org = await _mkuser()
    now = datetime.now(timezone.utc)
    # 3 close-in-time-and-space "person" + 1 far-away "vehicle"
    await _mk_dets(org, [
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=10),
         "drone_id": uuid4()},
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=8),
         "drone_id": uuid4()},
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=6),
         "drone_id": uuid4()},
        {"label": "vehicle", "lat": 30.7, "lng": 104.5,
         "created_at": now - timedelta(seconds=5),
         "drone_id": uuid4()},
    ])
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_detections"] == 4
    assert body["cluster_count"] == 2
    labels = sorted([c["label"] for c in body["clusters"]])
    assert labels == ["person", "vehicle"]
    person = next(c for c in body["clusters"] if c["label"] == "person")
    assert person["member_count"] == 3
    # by_label sanity
    by = {s["label"]: s for s in body["by_label"]}
    assert by["person"]["count"] == 3
    assert by["vehicle"]["count"] == 1


async def test_analytics_label_filter(client) -> None:
    tok, _, org = await _mkuser()
    now = datetime.now(timezone.utc)
    await _mk_dets(org, [
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=5)},
        {"label": "vehicle", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=3)},
    ])
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60"
        "&label=vehicle",
        headers=_h(tok),
    )
    body = r.json()
    assert body["total_detections"] == 1
    assert body["cluster_count"] == 1
    assert body["clusters"][0]["label"] == "vehicle"


async def test_analytics_since_filter(client) -> None:
    tok, _, org = await _mkuser()
    now = datetime.now(timezone.utc)
    await _mk_dets(org, [
        # Old — should be excluded by since_seconds=60
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=3600)},
        # Recent
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=5)},
    ])
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60",
        headers=_h(tok),
    )
    body = r.json()
    assert body["total_detections"] == 1


async def test_analytics_org_isolation(client) -> None:
    tok_a, _, org_a = await _mkuser()
    tok_b, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    await _mk_dets(org_a, [
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=5)},
    ])
    # B sees nothing.
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60",
        headers=_h(tok_b),
    )
    assert r.json()["total_detections"] == 0
    # A sees own.
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60",
        headers=_h(tok_a),
    )
    assert r.json()["total_detections"] == 1


async def test_analytics_geo_tol_param(client) -> None:
    tok, _, org = await _mkuser()
    now = datetime.now(timezone.utc)
    await _mk_dets(org, [
        {"label": "person", "lat": 30.6, "lng": 104.0,
         "created_at": now - timedelta(seconds=10)},
        # ~110m away (roughly 0.001 degree lat)
        {"label": "person", "lat": 30.601, "lng": 104.0,
         "created_at": now - timedelta(seconds=8)},
    ])
    # Default geo_tol_m=50 → 2 clusters
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60",
        headers=_h(tok),
    )
    assert r.json()["cluster_count"] == 2
    # geo_tol_m=200 → 1 cluster
    r = await client.get(
        "/api/v1/vision/analytics/clusters?since_seconds=60"
        "&geo_tol_m=200",
        headers=_h(tok),
    )
    assert r.json()["cluster_count"] == 1
