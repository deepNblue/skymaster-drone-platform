"""E3.1 · Vision detection analytics — clusters & label stats."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.detection_cluster import cluster_analytics


router = APIRouter(prefix="/vision", tags=["vision-analytics"])


@router.get("/analytics/clusters")
async def api_detection_clusters(
    label: str | None = None,
    since_seconds: int = Query(3600, ge=60, le=86_400),
    geo_tol_m: float = Query(50.0, gt=0, le=5000),
    time_tol_s: float = Query(30.0, gt=0, le=3600),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cluster VisionDetections by (label, spatial, temporal) proximity.

    Returns a dict with:
      window_seconds, total_detections, cluster_count,
      clusters[{label, member_count, centroid_lat/lng, first/last_seen_at,
                duration_s, peak_confidence, drone_ids[], member_ids[]}],
      by_label[{label, count, avg_confidence, peak_confidence,
                distinct_drones}]
    """
    return await cluster_analytics(
        db,
        tenant_id=user.org_id,
        label=label,
        since_seconds=since_seconds,
        geo_tol_m=geo_tol_m,
        time_tol_s=time_tol_s,
    )
