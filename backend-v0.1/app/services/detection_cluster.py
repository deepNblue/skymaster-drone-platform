"""E3.1 · Vision Detection clustering & analytics.

Problem: raw VisionDetection is per-frame-per-object; a person walking
past a hovering drone for 30s can produce 300+ "person" rows all with
the same GPS ± 5m. Operators drown, real alerts get lost.

Solution: cluster detections by (label, spatial proximity, time
window) into DetectionCluster summaries. Pure server-side aggregation
— no new tables (yet), no writes. This lays the groundwork for E3.2
DetectionAlertRule that will fire on cluster.member_count thresholds.

Constants
---------
GEO_TOL_M         50m default clustering radius (rough drone GPS jitter)
TIME_TOL_S        30s default window inside a cluster
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vision_copilot import VisionDetection


DEFAULT_GEO_TOL_M = 50.0
DEFAULT_TIME_TOL_S = 30.0
EARTH_R_M = 6_371_000.0


def _haversine_m(
    lat1: float, lng1: float, lat2: float, lng2: float,
) -> float:
    """Distance in meters between two lat/lng points."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    )
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def cluster_detections(
    rows: Iterable[dict[str, Any]],
    *,
    geo_tol_m: float = DEFAULT_GEO_TOL_M,
    time_tol_s: float = DEFAULT_TIME_TOL_S,
) -> list[dict[str, Any]]:
    """Pure clustering — no DB needed, easy to test.

    Input dict schema (minimal):
        {id, label, confidence, lat, lng, created_at (datetime)}
    Returns list of clusters, each:
        {label, member_count, first_seen_at, last_seen_at,
         centroid_lat, centroid_lng, peak_confidence,
         drone_ids [uniq], member_ids}
    Rows without lat/lng or created_at are silently skipped.
    Rows sorted by created_at ASC internally so cluster time bounds
    are deterministic.
    """
    valid: list[dict[str, Any]] = []
    for r in rows:
        if (
            r.get("lat") is None
            or r.get("lng") is None
            or r.get("created_at") is None
            or r.get("label") is None
        ):
            continue
        # Normalize naive datetimes to UTC-aware for arithmetic safety.
        ca = r["created_at"]
        if isinstance(ca, datetime) and ca.tzinfo is None:
            r = dict(r)
            r["created_at"] = ca.replace(tzinfo=timezone.utc)
        valid.append(r)
    valid.sort(key=lambda r: r["created_at"])

    clusters: list[dict[str, Any]] = []
    for r in valid:
        placed = False
        for c in clusters:
            if c["label"] != r["label"]:
                continue
            # Time gap: allow entering cluster if within window of
            # its current last_seen_at.
            gap_s = (
                r["created_at"] - c["last_seen_at"]
            ).total_seconds()
            if gap_s > time_tol_s:
                continue
            d_m = _haversine_m(
                c["centroid_lat"], c["centroid_lng"],
                float(r["lat"]), float(r["lng"]),
            )
            if d_m > geo_tol_m:
                continue

            # Accept — update centroid (running average).
            n = c["member_count"]
            c["centroid_lat"] = (
                c["centroid_lat"] * n + float(r["lat"])
            ) / (n + 1)
            c["centroid_lng"] = (
                c["centroid_lng"] * n + float(r["lng"])
            ) / (n + 1)
            c["member_count"] = n + 1
            c["last_seen_at"] = r["created_at"]
            conf = float(r.get("confidence") or 0)
            if conf > c["peak_confidence"]:
                c["peak_confidence"] = conf
            did = r.get("drone_id")
            if did is not None and did not in c["drone_ids"]:
                c["drone_ids"].append(did)
            c["member_ids"].append(r.get("id"))
            placed = True
            break
        if not placed:
            drone_id = r.get("drone_id")
            clusters.append({
                "label": r["label"],
                "member_count": 1,
                "first_seen_at": r["created_at"],
                "last_seen_at": r["created_at"],
                "centroid_lat": float(r["lat"]),
                "centroid_lng": float(r["lng"]),
                "peak_confidence": float(r.get("confidence") or 0),
                "drone_ids": [drone_id] if drone_id is not None else [],
                "member_ids": [r.get("id")],
            })
    return clusters


def compute_label_stats(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group by label → count / avg confidence / drones involved."""
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        lab = r.get("label")
        if lab is None:
            continue
        b = by.setdefault(lab, {
            "label": lab,
            "count": 0,
            "sum_confidence": 0.0,
            "peak_confidence": 0.0,
            "drone_ids": set(),
        })
        b["count"] += 1
        conf = float(r.get("confidence") or 0)
        b["sum_confidence"] += conf
        if conf > b["peak_confidence"]:
            b["peak_confidence"] = conf
        did = r.get("drone_id")
        if did is not None:
            b["drone_ids"].add(did)
    out: list[dict[str, Any]] = []
    for b in by.values():
        n = b["count"] or 1
        out.append({
            "label": b["label"],
            "count": b["count"],
            "avg_confidence": round(b["sum_confidence"] / n, 4),
            "peak_confidence": round(b["peak_confidence"], 4),
            "distinct_drones": len(b["drone_ids"]),
        })
    out.sort(key=lambda x: (-x["count"], x["label"]))
    return out


async def load_recent_detections(
    db: AsyncSession, *,
    tenant_id: uuid.UUID | None,
    label: str | None = None,
    since: datetime | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Load detection rows as dicts within a time window."""
    q = select(VisionDetection)
    if tenant_id is not None:
        q = q.where(VisionDetection.tenant_id == tenant_id)
    if label is not None:
        q = q.where(VisionDetection.label == label)
    if since is not None:
        q = q.where(VisionDetection.created_at >= since)
    q = q.order_by(desc(VisionDetection.created_at)).limit(min(limit, 5000))
    rows = (await db.execute(q)).scalars().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        ca = r.created_at
        if ca is not None and ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        out.append({
            "id": str(r.id),
            "label": r.label,
            "confidence": r.confidence,
            "lat": r.lat,
            "lng": r.lng,
            "created_at": ca,
            "drone_id": str(r.drone_id) if r.drone_id else None,
            "mission_id": str(r.mission_id) if r.mission_id else None,
        })
    return out


async def cluster_analytics(
    db: AsyncSession, *,
    tenant_id: uuid.UUID | None,
    label: str | None = None,
    since_seconds: int = 3600,
    geo_tol_m: float = DEFAULT_GEO_TOL_M,
    time_tol_s: float = DEFAULT_TIME_TOL_S,
) -> dict[str, Any]:
    """Full REST-facing entry point: fetch rows, cluster, summarise."""
    since = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
    rows = await load_recent_detections(
        db, tenant_id=tenant_id, label=label, since=since,
    )
    clusters = cluster_detections(
        rows, geo_tol_m=geo_tol_m, time_tol_s=time_tol_s,
    )
    stats = compute_label_stats(rows)
    return {
        "window_seconds": since_seconds,
        "total_detections": len(rows),
        "cluster_count": len(clusters),
        "clusters": [
            {
                **c,
                "first_seen_at": c["first_seen_at"].isoformat(),
                "last_seen_at": c["last_seen_at"].isoformat(),
                "duration_s": (
                    c["last_seen_at"] - c["first_seen_at"]
                ).total_seconds(),
            }
            for c in clusters
        ],
        "by_label": stats,
    }
