"""E2.5b · Airspace calendar service — CRUD + conflict detection.

The interesting method is ``find_conflicts``: given a proposed
(polygon, time range, altitude), it returns every existing entry
that overlaps in time AND bbox AND (if provided) altitude band.

Bounding-box overlap keeps the SQL cheap. Precise polygon-vs-polygon
intersection is a v2.1 upgrade (PostGIS + ST_Intersects).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airspace_calendar import AirspaceCalendarEntry, VALID_SOURCES


class CalendarError(Exception):
    """Domain error, mapped to HTTP 400/404 at REST layer."""


def _bbox(polygon: list) -> tuple[float, float, float, float]:
    """Compute (min_lon, min_lat, max_lon, max_lat) from a polygon.

    A polygon is a list of [lon, lat] pairs. Raises CalendarError if
    empty or malformed.
    """
    if not polygon:
        raise CalendarError("polygon must have at least one vertex")
    try:
        lons = [float(p[0]) for p in polygon]
        lats = [float(p[1]) for p in polygon]
    except (IndexError, TypeError, ValueError) as exc:
        raise CalendarError(
            "each polygon vertex must be [lon, lat]"
        ) from exc
    return min(lons), min(lats), max(lons), max(lats)


async def create_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    source: str,
    title: str,
    geo_polygon: list,
    start_ts: datetime,
    end_ts: datetime,
    purpose: str | None = None,
    external_ref: str | None = None,
    approval_id: uuid.UUID | None = None,
    min_alt_m: float | None = None,
    max_alt_m: float | None = None,
    priority: int = 10,
) -> AirspaceCalendarEntry:
    if source not in VALID_SOURCES:
        raise CalendarError(f"invalid source: {source}")
    if start_ts >= end_ts:
        raise CalendarError("start_ts must be earlier than end_ts")
    if not title.strip():
        raise CalendarError("title is required")

    min_lon, min_lat, max_lon, max_lat = _bbox(geo_polygon)
    row = AirspaceCalendarEntry(
        org_id=org_id,
        source=source,
        external_ref=external_ref,
        approval_id=approval_id,
        title=title.strip(),
        purpose=purpose,
        geo_polygon=geo_polygon,
        bbox_min_lon=min_lon,
        bbox_min_lat=min_lat,
        bbox_max_lon=max_lon,
        bbox_max_lat=max_lat,
        min_alt_m=min_alt_m,
        max_alt_m=max_alt_m,
        start_ts=start_ts,
        end_ts=end_ts,
        priority=priority,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    source: str | None = None,
    limit: int = 200,
) -> list[AirspaceCalendarEntry]:
    q = select(AirspaceCalendarEntry).where(
        AirspaceCalendarEntry.org_id == org_id,
        AirspaceCalendarEntry.deleted_at.is_(None),
    )
    # Time range overlap: existing entry overlaps [start, end] iff
    # entry.end_ts > start AND entry.start_ts < end.
    if start_ts is not None:
        q = q.where(AirspaceCalendarEntry.end_ts > start_ts)
    if end_ts is not None:
        q = q.where(AirspaceCalendarEntry.start_ts < end_ts)
    if source is not None:
        if source not in VALID_SOURCES:
            raise CalendarError(f"invalid source filter: {source}")
        q = q.where(AirspaceCalendarEntry.source == source)
    q = q.order_by(AirspaceCalendarEntry.start_ts.asc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def get_entry(
    db: AsyncSession, *, org_id: uuid.UUID, entry_id: uuid.UUID,
) -> AirspaceCalendarEntry | None:
    q = select(AirspaceCalendarEntry).where(
        AirspaceCalendarEntry.id == entry_id,
        AirspaceCalendarEntry.org_id == org_id,
        AirspaceCalendarEntry.deleted_at.is_(None),
    )
    return (await db.execute(q)).scalar_one_or_none()


async def delete_entry(
    db: AsyncSession, *, org_id: uuid.UUID, entry_id: uuid.UUID,
) -> bool:
    row = await get_entry(db, org_id=org_id, entry_id=entry_id)
    if row is None:
        return False
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def find_conflicts(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    polygon: list,
    start_ts: datetime,
    end_ts: datetime,
    min_alt_m: float | None = None,
    max_alt_m: float | None = None,
    exclude_ids: Iterable[uuid.UUID] = (),
) -> list[AirspaceCalendarEntry]:
    """Return existing calendar entries that overlap the proposed window.

    Overlap rules:
      * Time: entry.end_ts > start_ts AND entry.start_ts < end_ts
      * Bbox: NOT (entry_max_lon < req_min_lon OR entry_min_lon > req_max_lon
              OR entry_max_lat < req_min_lat OR entry_min_lat > req_max_lat)
      * Altitude (if both sides specify): band overlap
    """
    if start_ts >= end_ts:
        raise CalendarError("start_ts must be earlier than end_ts")
    req_min_lon, req_min_lat, req_max_lon, req_max_lat = _bbox(polygon)

    q = select(AirspaceCalendarEntry).where(
        AirspaceCalendarEntry.org_id == org_id,
        AirspaceCalendarEntry.deleted_at.is_(None),
        AirspaceCalendarEntry.end_ts > start_ts,
        AirspaceCalendarEntry.start_ts < end_ts,
        AirspaceCalendarEntry.bbox_max_lon >= req_min_lon,
        AirspaceCalendarEntry.bbox_min_lon <= req_max_lon,
        AirspaceCalendarEntry.bbox_max_lat >= req_min_lat,
        AirspaceCalendarEntry.bbox_min_lat <= req_max_lat,
    )
    if exclude_ids:
        q = q.where(~AirspaceCalendarEntry.id.in_(list(exclude_ids)))

    rows = list((await db.execute(q)).scalars().all())

    # Altitude filter — only apply when BOTH sides define a band.
    if min_alt_m is not None or max_alt_m is not None:
        req_min = min_alt_m if min_alt_m is not None else float("-inf")
        req_max = max_alt_m if max_alt_m is not None else float("inf")
        keep: list[AirspaceCalendarEntry] = []
        for r in rows:
            if r.min_alt_m is None and r.max_alt_m is None:
                keep.append(r)  # unconstrained entry conflicts with anything
                continue
            e_min = r.min_alt_m if r.min_alt_m is not None else float("-inf")
            e_max = r.max_alt_m if r.max_alt_m is not None else float("inf")
            if e_max >= req_min and e_min <= req_max:
                keep.append(r)
        rows = keep
    return rows


def summarize_conflict(entry: AirspaceCalendarEntry) -> dict[str, Any]:
    """Compact dict for API responses / UI badges."""
    return {
        "id": str(entry.id),
        "source": entry.source,
        "title": entry.title,
        "start_ts": entry.start_ts.isoformat(),
        "end_ts": entry.end_ts.isoformat(),
        "min_alt_m": entry.min_alt_m,
        "max_alt_m": entry.max_alt_m,
        "priority": entry.priority,
        "external_ref": entry.external_ref,
        "approval_id": (
            str(entry.approval_id) if entry.approval_id else None
        ),
    }
