"""D3.3 · 4DGS frame diff REST endpoints."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.frame_diff import (
    diff_between_indices, timeline_change_report,
)
from app.services.scene_frame import FrameError


router = APIRouter(tags=["frame-diff"])


def _map(exc: FrameError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.get("/scenes/{scene_id}/frames/diff")
async def api_diff_between(
    scene_id: UUID,
    a: int = Query(..., ge=0, description="from frame_index"),
    b: int = Query(..., ge=0, description="to frame_index"),
    psnr_warn: float = 3.0,
    psnr_crit: float = 6.0,
    time_warn_s: float = 60.0,
    time_crit_s: float = 300.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await diff_between_indices(
            db,
            scene_id=scene_id, org_id=user.org_id,
            a=a, b=b,
            psnr_warn=psnr_warn, psnr_crit=psnr_crit,
            time_warn_s=time_warn_s, time_crit_s=time_crit_s,
        )
    except FrameError as exc:
        raise _map(exc)


@router.get("/scenes/{scene_id}/frames/changes")
async def api_change_report(
    scene_id: UUID,
    min_severity: str = "low",
    psnr_warn: float = 3.0,
    psnr_crit: float = 6.0,
    time_warn_s: float = 60.0,
    time_crit_s: float = 300.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await timeline_change_report(
            db,
            scene_id=scene_id, org_id=user.org_id,
            min_severity=min_severity,
            psnr_warn=psnr_warn, psnr_crit=psnr_crit,
            time_warn_s=time_warn_s, time_crit_s=time_crit_s,
        )
    except FrameError as exc:
        raise _map(exc)
