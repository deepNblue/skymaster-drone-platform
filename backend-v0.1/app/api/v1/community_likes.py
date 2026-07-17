"""F3.2 · Community likes + trending REST."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.community_like import (
    LikeError, add_like, like_status, remove_like, trending_posts,
)


router = APIRouter(prefix="/community", tags=["community-likes"])


def _map(exc: LikeError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post("/likes/{post_id}", status_code=201)
async def api_like(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await add_like(db, user_id=user.id, post_id=post_id)
    except LikeError as e:
        raise _map(e)


@router.delete("/likes/{post_id}", status_code=200)
async def api_unlike(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await remove_like(db, user_id=user.id, post_id=post_id)
    except LikeError as e:
        raise _map(e)


@router.get("/likes/{post_id}/status")
async def api_like_status(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await like_status(
            db, user_id=user.id, post_id=post_id,
        )
    except LikeError as e:
        raise _map(e)


@router.get("/trending")
async def api_trending(
    within_hours: int = Query(72, ge=1, le=720),
    limit: int = Query(20, ge=1, le=100),
    tenant_scope: bool = Query(
        False, description="If true, restrict to caller's org",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await trending_posts(
        db,
        tenant_id=user.org_id if tenant_scope else None,
        within_hours=within_hours,
        limit=limit,
    )
