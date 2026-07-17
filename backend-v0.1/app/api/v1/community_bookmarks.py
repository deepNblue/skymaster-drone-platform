"""F3.1 · Community bookmark REST."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.community_bookmark import (
    BookmarkError, add_bookmark, count_bookmarks_for_post, is_bookmarked,
    list_bookmarks, remove_bookmark,
)


router = APIRouter(prefix="/community/bookmarks", tags=["community-bookmarks"])


@router.get("")
async def api_list(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await list_bookmarks(
        db, user_id=user.id, limit=limit, offset=offset,
    )


@router.post("/{post_id}", status_code=201)
async def api_add(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        bm = await add_bookmark(db, user_id=user.id, post_id=post_id)
    except BookmarkError as e:
        raise HTTPException(400 if "found" not in str(e) else 404, str(e))
    total = await count_bookmarks_for_post(db, post_id=post_id)
    return {
        "post_id": str(bm.post_id),
        "bookmarked_at": bm.created_at.isoformat(),
        "total_bookmarks": total,
    }


@router.delete("/{post_id}", status_code=204)
async def api_remove(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await remove_bookmark(db, user_id=user.id, post_id=post_id)


@router.get("/{post_id}/status")
async def api_status(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Whether the current user has bookmarked this post + total count."""
    bookmarked = await is_bookmarked(
        db, user_id=user.id, post_id=post_id,
    )
    total = await count_bookmarks_for_post(db, post_id=post_id)
    return {
        "post_id": str(post_id),
        "bookmarked": bookmarked,
        "total_bookmarks": total,
    }
