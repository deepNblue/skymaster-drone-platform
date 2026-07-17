"""F3.1 · Community bookmark service — add/remove/list."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import CommunityPost
from app.models.community_bookmark import CommunityBookmark


class BookmarkError(Exception):
    pass


async def add_bookmark(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> CommunityBookmark:
    """Idempotent: creating an existing bookmark is a no-op."""
    # Verify post exists & is not rejected/archived.
    q = select(CommunityPost).where(CommunityPost.id == post_id)
    post = (await db.execute(q)).scalar_one_or_none()
    if post is None:
        raise BookmarkError("post not found")
    if post.moderation_status in ("rejected", "archived"):
        raise BookmarkError(f"post is {post.moderation_status}")

    existing = await db.get(CommunityBookmark, (user_id, post_id))
    if existing is not None:
        return existing
    bm = CommunityBookmark(user_id=user_id, post_id=post_id)
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    return bm


async def remove_bookmark(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> bool:
    """Idempotent: removing a non-existent bookmark returns False."""
    existing = await db.get(CommunityBookmark, (user_id, post_id))
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True


async def is_bookmarked(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> bool:
    q = select(exists().where(
        CommunityBookmark.user_id == user_id,
        CommunityBookmark.post_id == post_id,
    ))
    return bool((await db.execute(q)).scalar())


async def list_bookmarks(
    db: AsyncSession, *, user_id: uuid.UUID,
    limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    """Return bookmarked posts, most recent bookmark first."""
    q = (
        select(CommunityBookmark, CommunityPost)
        .join(CommunityPost, CommunityPost.id == CommunityBookmark.post_id)
        .where(CommunityBookmark.user_id == user_id)
        .order_by(CommunityBookmark.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "post_id": str(post.id),
            "bookmarked_at": bm.created_at.isoformat(),
            "title": post.title,
            "tags": post.tags or [],
            "moderation_status": post.moderation_status,
            "view_count": post.view_count,
            "like_count": post.like_count,
            "comment_count": post.comment_count,
            "created_at": post.created_at.isoformat(),
        }
        for bm, post in rows
    ]


async def count_bookmarks_for_post(
    db: AsyncSession, *, post_id: uuid.UUID,
) -> int:
    q = select(func.count()).select_from(CommunityBookmark).where(
        CommunityBookmark.post_id == post_id,
    )
    return int((await db.execute(q)).scalar() or 0)
