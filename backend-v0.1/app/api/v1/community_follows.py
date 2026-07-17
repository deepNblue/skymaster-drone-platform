"""F3.3 · Community follow REST."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.community_follow import (
    FollowError, follow_counts, follow_user, followed_feed,
    is_following, list_followers, list_following, unfollow_user,
)


router = APIRouter(prefix="/community", tags=["community-follows"])


def _map(exc: FollowError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post("/follows/{target_id}", status_code=201)
async def api_follow(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await follow_user(
            db, follower_id=user.id, followed_id=target_id,
        )
    except FollowError as e:
        raise _map(e)


@router.delete("/follows/{target_id}", status_code=204)
async def api_unfollow(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await unfollow_user(
        db, follower_id=user.id, followed_id=target_id,
    )


@router.get("/follows/{target_id}/status")
async def api_status(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    following = await is_following(
        db, follower_id=user.id, followed_id=target_id,
    )
    return {
        "target_id": str(target_id), "following": following,
    }


@router.get("/follows/me/counts")
async def api_my_counts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    return await follow_counts(db, user_id=user.id)


@router.get("/follows/me/following")
async def api_my_following(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await list_following(
        db, user_id=user.id, limit=limit, offset=offset,
    )


@router.get("/follows/me/followers")
async def api_my_followers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await list_followers(
        db, user_id=user.id, limit=limit, offset=offset,
    )


@router.get("/follows/feed")
async def api_feed(
    within_hours: int = Query(168, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await followed_feed(
        db, user_id=user.id,
        within_hours=within_hours, limit=limit, offset=offset,
    )
