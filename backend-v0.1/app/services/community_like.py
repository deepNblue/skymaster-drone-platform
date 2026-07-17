"""F3.2 · Community like service + trending hot-score."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import CommunityLike, CommunityPost


# Hot score decay half-life (hours).
HOT_HALF_LIFE_H = 24.0


class LikeError(Exception):
    pass


# ------------------------- Like CRUD -------------------------

async def add_like(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> dict[str, Any]:
    """Idempotent add; also updates the post's `like_count`."""
    post = (await db.execute(
        select(CommunityPost).where(CommunityPost.id == post_id),
    )).scalar_one_or_none()
    if post is None:
        raise LikeError("post not found")
    if post.moderation_status in ("rejected", "archived"):
        raise LikeError(f"post is {post.moderation_status}")

    existing = (await db.execute(
        select(CommunityLike).where(
            CommunityLike.user_id == user_id,
            CommunityLike.post_id == post_id,
        ),
    )).scalar_one_or_none()
    if existing is not None:
        return {
            "post_id": str(post_id),
            "liked": True,
            "like_count": post.like_count,
        }

    like = CommunityLike(user_id=user_id, post_id=post_id)
    db.add(like)
    post.like_count = (post.like_count or 0) + 1
    await db.commit()
    await db.refresh(post)
    return {
        "post_id": str(post_id),
        "liked": True,
        "like_count": post.like_count,
    }


async def remove_like(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> dict[str, Any]:
    """Idempotent remove; also decrements `like_count` if it existed."""
    post = (await db.execute(
        select(CommunityPost).where(CommunityPost.id == post_id),
    )).scalar_one_or_none()
    if post is None:
        raise LikeError("post not found")

    existing = (await db.execute(
        select(CommunityLike).where(
            CommunityLike.user_id == user_id,
            CommunityLike.post_id == post_id,
        ),
    )).scalar_one_or_none()
    if existing is None:
        return {
            "post_id": str(post_id),
            "liked": False,
            "like_count": post.like_count,
        }
    await db.delete(existing)
    post.like_count = max(0, (post.like_count or 0) - 1)
    await db.commit()
    await db.refresh(post)
    return {
        "post_id": str(post_id),
        "liked": False,
        "like_count": post.like_count,
    }


async def is_liked(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> bool:
    q = select(exists().where(
        CommunityLike.user_id == user_id,
        CommunityLike.post_id == post_id,
    ))
    return bool((await db.execute(q)).scalar())


async def like_status(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID,
) -> dict[str, Any]:
    post = (await db.execute(
        select(CommunityPost).where(CommunityPost.id == post_id),
    )).scalar_one_or_none()
    if post is None:
        raise LikeError("post not found")
    liked = await is_liked(db, user_id=user_id, post_id=post_id)
    return {
        "post_id": str(post_id),
        "liked": liked,
        "like_count": post.like_count,
    }


# ------------------------- Trending -------------------------

def compute_hot_score(
    likes: int, views: int, comments: int, age_hours: float,
    *, half_life_h: float = HOT_HALF_LIFE_H,
) -> float:
    """Reddit-style time-decayed hot score.

    Combines weighted engagement (likes 3× > comments 2× > views)
    with exponential time decay. Newer posts score higher for the
    same engagement.
    """
    engagement = 3.0 * max(likes, 0) + 2.0 * max(comments, 0) + \
        0.1 * max(views, 0)
    # log1p keeps scores bounded for viral posts (top-of-log-scale)
    base = math.log1p(engagement)
    if age_hours < 0:
        age_hours = 0
    decay = math.pow(0.5, age_hours / max(half_life_h, 0.1))
    return base * decay


async def trending_posts(
    db: AsyncSession, *,
    tenant_id: uuid.UUID | None = None,
    within_hours: int = 72,
    limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N approved posts by hot_score within a window."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=within_hours)

    q = select(CommunityPost).where(
        CommunityPost.moderation_status == "approved",
        CommunityPost.created_at >= since,
    )
    if tenant_id is not None:
        q = q.where(CommunityPost.tenant_id == tenant_id)
    q = q.order_by(CommunityPost.created_at.desc()).limit(200)
    posts = list((await db.execute(q)).scalars().all())

    scored: list[dict[str, Any]] = []
    for p in posts:
        ca = p.created_at
        if ca is not None and ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - ca).total_seconds() / 3600.0)
        score = compute_hot_score(
            likes=p.like_count or 0,
            views=p.view_count or 0,
            comments=p.comment_count or 0,
            age_hours=age_h,
        )
        scored.append({
            "post_id": str(p.id),
            "title": p.title,
            "tags": p.tags or [],
            "author_id": str(p.author_id) if p.author_id else None,
            "like_count": p.like_count,
            "view_count": p.view_count,
            "comment_count": p.comment_count,
            "created_at": ca.isoformat() if ca else None,
            "age_hours": round(age_h, 2),
            "hot_score": round(score, 4),
        })
    scored.sort(key=lambda r: r["hot_score"], reverse=True)
    return scored[:limit]


async def like_count_for_post(
    db: AsyncSession, *, post_id: uuid.UUID,
) -> int:
    """Authoritative count directly from likes table (not cache)."""
    q = select(func.count()).select_from(CommunityLike).where(
        CommunityLike.post_id == post_id,
    )
    return int((await db.execute(q)).scalar() or 0)
