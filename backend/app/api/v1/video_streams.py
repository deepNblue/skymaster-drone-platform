"""Video stream registry API — R21 Step H.

RTSP/RTMP/HLS live-video source registry. This is orchestration only —
actual pixels flow through an external SRS/MediaMTX/go2rtc gateway.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import AnyUrl, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.video_stream import VideoStream, VideoStreamProbe
from app.services.video_streams import (
    PROTOCOLS, STATUSES, is_stale, normalize_protocol, run_ffprobe,
)

router = APIRouter(prefix="/video-streams", tags=["video-streams"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class StreamIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=8, max_length=1024)
    play_url: Optional[str] = Field(None, max_length=1024)
    drone_id: Optional[UUID] = None
    protocol: Optional[str] = None  # inferred from source_url if omitted
    status: Optional[str] = None
    meta: Optional[dict] = None


class StreamPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    play_url: Optional[str] = Field(None, max_length=1024)
    status: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    meta: Optional[dict] = None


class StreamOut(BaseModel):
    id: UUID
    drone_id: Optional[UUID] = None
    name: str
    protocol: str
    source_url: str
    play_url: Optional[str] = None
    status: str
    bitrate_kbps: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    meta: Optional[dict] = None
    last_seen_at: Optional[datetime] = None
    stale: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ProbeOut(BaseModel):
    id: UUID
    stream_id: UUID
    probe_status: str
    reason: Optional[str] = None
    payload: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(row: VideoStream) -> StreamOut:
    return StreamOut(
        id=row.id, drone_id=row.drone_id, name=row.name,
        protocol=row.protocol, source_url=row.source_url,
        play_url=row.play_url, status=row.status,
        bitrate_kbps=row.bitrate_kbps, width=row.width, height=row.height,
        fps=row.fps, codec=row.codec, meta=row.meta,
        last_seen_at=row.last_seen_at,
        stale=is_stale(row.last_seen_at) if row.status == "active" else False,
        created_at=row.created_at,
    )


def _require_writer(user: User) -> None:
    role = getattr(user, "role", None)
    if role not in {"admin", "operator"}:
        raise HTTPException(403, "admin or operator only")


def _validate_protocol(p: str | None) -> None:
    if p and p not in PROTOCOLS:
        raise HTTPException(400, f"protocol must be one of {list(PROTOCOLS)}")


def _validate_status(s: str | None) -> None:
    if s and s not in STATUSES:
        raise HTTPException(400, f"status must be one of {list(STATUSES)}")


# ---------------------------------------------------------------------------
# CRUD + registry
# ---------------------------------------------------------------------------


@router.post("", response_model=StreamOut, status_code=201)
async def register_stream(
    body: StreamIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamOut:
    _require_writer(user)
    _validate_protocol(body.protocol)
    _validate_status(body.status)
    proto = body.protocol or normalize_protocol(body.source_url)
    row = VideoStream(
        drone_id=body.drone_id,
        name=body.name,
        protocol=proto,
        source_url=body.source_url,
        play_url=body.play_url,
        status=body.status or "idle",
        meta=body.meta,
        created_by=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.get("", response_model=list[StreamOut])
async def list_streams(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    drone_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    protocol: Optional[str] = None,
    limit: int = Query(100, le=500),
) -> list[StreamOut]:
    _validate_protocol(protocol)
    _validate_status(status_filter)
    q = select(VideoStream).order_by(VideoStream.created_at.desc()).limit(limit)
    if drone_id:
        q = q.where(VideoStream.drone_id == drone_id)
    if status_filter:
        q = q.where(VideoStream.status == status_filter)
    if protocol:
        q = q.where(VideoStream.protocol == protocol)
    rows = list((await db.execute(q)).scalars().all())
    return [_to_out(r) for r in rows]


@router.get("/{stream_id}", response_model=StreamOut)
async def get_stream(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamOut:
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    return _to_out(row)


@router.patch("/{stream_id}", response_model=StreamOut)
async def patch_stream(
    stream_id: UUID,
    body: StreamPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamOut:
    _require_writer(user)
    _validate_status(body.status)
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    for field_name, val in body.model_dump(exclude_unset=True).items():
        setattr(row, field_name, val)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.post("/{stream_id}/heartbeat", response_model=StreamOut)
async def heartbeat_stream(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamOut:
    """Called by the publisher (drone gateway / RTMP endpoint) to signal
    a stream is alive. Also flips ``idle`` → ``active``."""
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    row.last_seen_at = datetime.now(timezone.utc)
    if row.status == "idle":
        row.status = "active"
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.post("/{stream_id}/stop", response_model=StreamOut)
async def stop_stream(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamOut:
    _require_writer(user)
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    row.status = "stopped"
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.post("/{stream_id}/probe", response_model=ProbeOut)
async def probe_stream(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProbeOut:
    _require_writer(user)
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    result = await run_ffprobe(row.source_url)
    st = result.get("status", "error")
    probe = VideoStreamProbe(
        stream_id=row.id,
        probe_status=st,
        reason=result.get("reason"),
        payload=result,
    )
    db.add(probe)

    # Backfill known metadata on success.
    if st == "ok":
        row.codec = result.get("codec") or row.codec
        row.width = result.get("width") or row.width
        row.height = result.get("height") or row.height
        row.fps = result.get("fps") or row.fps
        br = result.get("bit_rate")
        if br:
            row.bitrate_kbps = int(br) // 1000
    elif st == "error":
        row.status = "error"
    await db.commit()
    await db.refresh(probe)
    return ProbeOut(
        id=probe.id, stream_id=probe.stream_id,
        probe_status=probe.probe_status, reason=probe.reason,
        payload=probe.payload, created_at=probe.created_at,
    )


@router.get("/{stream_id}/probes", response_model=list[ProbeOut])
async def list_probes(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, le=200),
) -> list[ProbeOut]:
    q = (
        select(VideoStreamProbe)
        .where(VideoStreamProbe.stream_id == stream_id)
        .order_by(VideoStreamProbe.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(q)).scalars().all())
    return [
        ProbeOut(
            id=r.id, stream_id=r.stream_id, probe_status=r.probe_status,
            reason=r.reason, payload=r.payload, created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/{stream_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def delete_stream(
    stream_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_writer(user)
    row = await db.get(VideoStream, stream_id)
    if row is None:
        raise HTTPException(404, "stream not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.get("/stats/summary")
async def stream_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(VideoStream.status, func.count()).group_by(VideoStream.status)
    by_status = {s: int(n) for s, n in (await db.execute(q)).all()}
    q2 = select(VideoStream.protocol, func.count()).group_by(VideoStream.protocol)
    by_proto = {s: int(n) for s, n in (await db.execute(q2)).all()}
    return {"by_status": by_status, "by_protocol": by_proto}
