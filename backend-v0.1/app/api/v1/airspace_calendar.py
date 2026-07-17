"""E2.5b · Airspace calendar REST endpoints.

POST   /airspace-calendar                  create entry
GET    /airspace-calendar                  list (time range + source filter)
GET    /airspace-calendar/{id}             fetch one
DELETE /airspace-calendar/{id}             soft delete
POST   /airspace-calendar/check-conflicts  probe without persisting
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.airspace_calendar import (
    CalendarError,
    create_entry,
    delete_entry,
    find_conflicts,
    get_entry,
    list_entries,
    summarize_conflict,
)


router = APIRouter(
    prefix="/airspace-calendar",
    tags=["airspace-calendar"],
)


class CalendarEntryOut(BaseModel):
    id: UUID
    org_id: UUID
    source: str
    external_ref: str | None
    approval_id: UUID | None
    title: str
    purpose: str | None
    geo_polygon: list
    bbox_min_lon: float
    bbox_min_lat: float
    bbox_max_lon: float
    bbox_max_lat: float
    min_alt_m: float | None
    max_alt_m: float | None
    start_ts: str
    end_ts: str
    priority: int
    created_at: str

    @classmethod
    def from_row(cls, r) -> "CalendarEntryOut":
        return cls(
            id=r.id,
            org_id=r.org_id,
            source=r.source,
            external_ref=r.external_ref,
            approval_id=r.approval_id,
            title=r.title,
            purpose=r.purpose,
            geo_polygon=r.geo_polygon,
            bbox_min_lon=r.bbox_min_lon,
            bbox_min_lat=r.bbox_min_lat,
            bbox_max_lon=r.bbox_max_lon,
            bbox_max_lat=r.bbox_max_lat,
            min_alt_m=r.min_alt_m,
            max_alt_m=r.max_alt_m,
            start_ts=r.start_ts.isoformat() if r.start_ts else "",
            end_ts=r.end_ts.isoformat() if r.end_ts else "",
            priority=r.priority,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )


class CreateEntryPayload(BaseModel):
    source: str = "local"
    title: str = Field(..., min_length=1, max_length=255)
    purpose: str | None = None
    external_ref: str | None = None
    approval_id: UUID | None = None
    geo_polygon: list
    start_ts: datetime
    end_ts: datetime
    min_alt_m: float | None = None
    max_alt_m: float | None = None
    priority: int = 10


class CheckConflictsPayload(BaseModel):
    geo_polygon: list
    start_ts: datetime
    end_ts: datetime
    min_alt_m: float | None = None
    max_alt_m: float | None = None
    exclude_ids: list[UUID] = Field(default_factory=list)


class ConflictsResponse(BaseModel):
    count: int
    conflicts: list[dict[str, Any]]


def _map_error(exc: CalendarError) -> HTTPException:
    return HTTPException(400, str(exc))


@router.post("", response_model=CalendarEntryOut, status_code=201)
async def api_create(
    payload: CreateEntryPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarEntryOut:
    try:
        row = await create_entry(
            db, org_id=user.org_id,
            source=payload.source,
            title=payload.title,
            geo_polygon=payload.geo_polygon,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            purpose=payload.purpose,
            external_ref=payload.external_ref,
            approval_id=payload.approval_id,
            min_alt_m=payload.min_alt_m,
            max_alt_m=payload.max_alt_m,
            priority=payload.priority,
        )
    except CalendarError as exc:
        raise _map_error(exc)
    return CalendarEntryOut.from_row(row)


@router.get("", response_model=list[CalendarEntryOut])
async def api_list(
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    source: str | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CalendarEntryOut]:
    try:
        rows = await list_entries(
            db, org_id=user.org_id,
            start_ts=start_ts, end_ts=end_ts, source=source,
            limit=min(max(limit, 1), 1000),
        )
    except CalendarError as exc:
        raise _map_error(exc)
    return [CalendarEntryOut.from_row(r) for r in rows]


@router.get("/{entry_id}", response_model=CalendarEntryOut)
async def api_get(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalendarEntryOut:
    row = await get_entry(db, org_id=user.org_id, entry_id=entry_id)
    if row is None:
        raise HTTPException(404, "calendar entry not found")
    return CalendarEntryOut.from_row(row)


@router.delete("/{entry_id}", status_code=204)
async def api_delete(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    ok = await delete_entry(db, org_id=user.org_id, entry_id=entry_id)
    if not ok:
        raise HTTPException(404, "calendar entry not found")


@router.post("/check-conflicts", response_model=ConflictsResponse)
async def api_check(
    payload: CheckConflictsPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConflictsResponse:
    try:
        rows = await find_conflicts(
            db, org_id=user.org_id,
            polygon=payload.geo_polygon,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            min_alt_m=payload.min_alt_m,
            max_alt_m=payload.max_alt_m,
            exclude_ids=payload.exclude_ids,
        )
    except CalendarError as exc:
        raise _map_error(exc)
    return ConflictsResponse(
        count=len(rows),
        conflicts=[summarize_conflict(r) for r in rows],
    )
