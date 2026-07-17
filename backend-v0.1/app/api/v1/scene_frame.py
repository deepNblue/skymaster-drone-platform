"""D3.1 · Scene frame REST — 4DGS timeline endpoints."""
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
from app.services.scene_frame import (
    FrameError, bulk_create_frames, create_frame, delete_frame, get_frame,
    list_frames, timeline_summary, update_frame,
)


router = APIRouter(tags=["scene-frame"])


class FrameOut(BaseModel):
    id: UUID
    scene_id: UUID
    frame_index: int
    captured_at: str | None
    is_keyframe: bool
    psnr_frame: float | None
    lighting: str | None
    notes: str | None
    meta: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r) -> "FrameOut":
        return cls(
            id=r.id,
            scene_id=r.scene_id,
            frame_index=r.frame_index,
            captured_at=r.captured_at.isoformat() if r.captured_at else None,
            is_keyframe=r.is_keyframe,
            psnr_frame=r.psnr_frame,
            lighting=r.lighting,
            notes=r.notes,
            meta=r.meta or {},
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )


class CreatePayload(BaseModel):
    frame_index: int = Field(..., ge=0)
    captured_at: datetime | None = None
    is_keyframe: bool = False
    psnr_frame: float | None = None
    lighting: str | None = None
    notes: str | None = None
    meta: dict[str, Any] | None = None


class UpdatePayload(BaseModel):
    is_keyframe: bool | None = None
    psnr_frame: float | None = None
    lighting: str | None = None
    notes: str | None = None
    captured_at: datetime | None = None
    meta: dict[str, Any] | None = None


class BulkCreatePayload(BaseModel):
    frames: list[CreatePayload]


def _map(exc: FrameError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post(
    "/scenes/{scene_id}/frames",
    response_model=FrameOut, status_code=201,
)
async def api_create_frame(
    scene_id: UUID,
    payload: CreatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FrameOut:
    try:
        row = await create_frame(
            db, scene_id=scene_id, org_id=user.org_id,
            frame_index=payload.frame_index,
            captured_at=payload.captured_at,
            is_keyframe=payload.is_keyframe,
            psnr_frame=payload.psnr_frame,
            lighting=payload.lighting,
            notes=payload.notes,
            meta=payload.meta,
        )
    except FrameError as exc:
        raise _map(exc)
    return FrameOut.from_row(row)


@router.post(
    "/scenes/{scene_id}/frames/bulk",
    response_model=list[FrameOut],
    status_code=201,
)
async def api_bulk_create_frames(
    scene_id: UUID,
    payload: BulkCreatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FrameOut]:
    try:
        rows = await bulk_create_frames(
            db, scene_id=scene_id, org_id=user.org_id,
            entries=[p.model_dump() for p in payload.frames],
        )
    except FrameError as exc:
        raise _map(exc)
    return [FrameOut.from_row(r) for r in rows]


@router.get(
    "/scenes/{scene_id}/frames",
    response_model=list[FrameOut],
)
async def api_list_frames(
    scene_id: UUID,
    only_keyframes: bool = False,
    lighting: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FrameOut]:
    try:
        rows = await list_frames(
            db, scene_id=scene_id, org_id=user.org_id,
            only_keyframes=only_keyframes,
            lighting=lighting,
        )
    except FrameError as exc:
        raise _map(exc)
    return [FrameOut.from_row(r) for r in rows]


@router.get(
    "/scenes/{scene_id}/frames/{frame_index}",
    response_model=FrameOut,
)
async def api_get_frame(
    scene_id: UUID,
    frame_index: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FrameOut:
    try:
        row = await get_frame(
            db, scene_id=scene_id, org_id=user.org_id,
            frame_index=frame_index,
        )
    except FrameError as exc:
        raise _map(exc)
    if row is None:
        raise HTTPException(404, "frame not found")
    return FrameOut.from_row(row)


@router.patch(
    "/scenes/{scene_id}/frames/{frame_index}",
    response_model=FrameOut,
)
async def api_update_frame(
    scene_id: UUID,
    frame_index: int,
    payload: UpdatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FrameOut:
    try:
        row = await update_frame(
            db, scene_id=scene_id, org_id=user.org_id,
            frame_index=frame_index,
            is_keyframe=payload.is_keyframe,
            psnr_frame=payload.psnr_frame,
            lighting=payload.lighting,
            notes=payload.notes,
            captured_at=payload.captured_at,
            meta=payload.meta,
        )
    except FrameError as exc:
        raise _map(exc)
    return FrameOut.from_row(row)


@router.delete(
    "/scenes/{scene_id}/frames/{frame_index}", status_code=204,
)
async def api_delete_frame(
    scene_id: UUID, frame_index: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        ok = await delete_frame(
            db, scene_id=scene_id, org_id=user.org_id,
            frame_index=frame_index,
        )
    except FrameError as exc:
        raise _map(exc)
    if not ok:
        raise HTTPException(404, "frame not found")


@router.get("/scenes/{scene_id}/timeline")
async def api_timeline(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await timeline_summary(
            db, scene_id=scene_id, org_id=user.org_id,
        )
    except FrameError as exc:
        raise _map(exc)
