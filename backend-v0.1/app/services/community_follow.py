"""F3.3 · Community follow service — follow/unfollow + feed."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import CommunityPost
from app.models.community_follow import CommunityFollow
from app.models.user import User


class FollowError(Exception):
    pass


# ------------------------- Follow / Unfollow -------------------------

async def follow_user(
    db: AsyncSession, *,
    follower_id: uuid.UUID, followed_id: uuid.UUID,
) -> dict[str, Any]:
    """Idempotent follow. Prevents self-follow at app + DB layer."""
    if follower_id == followed_id:
        raise FollowError("cannot follow yourself")
    # Verify target user exists.
    target = await db.get(User, followed_id)
    if target is None:
        raise FollowError("user not found")

    existing = await db.get(
        CommunityFollow, (follower_id, followed_id),
    )
    if existing is not None:
        return _serialize(existing, following=True)

    row = CommunityFollow(
        follower_id=follower_id, followed_id=followed_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize(row, following=True)


async def unfollow_user(
    db: AsyncSession, *,
    follower_id: uuid.UUID, followed_id: uuid.UUID,
) -> bool:
    """Idempotent unfollow. Returns True if a row was deleted."""
    existing = await db.get(
        CommunityFollow, (follower_id, followed_id),
    )
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True


async def is_following(
    db: AsyncSession, *,
    follower_id: uuid.UUID, followed_id: uuid.UUID,
) -> bool:
    q = select(exists().where(
        CommunityFollow.follower_id == follower_id,
        CommunityFollow.followed_id == followed_id,
    ))
    return bool((await db.execute(q)).scalar())


# ------------------------- Queries -------------------------

async def list_following(
    db: AsyncSession, *, user_id: uuid.UUID,
    limit: int = 100, offset: int = 0,
) -> list[dict[str, Any]]:
    """Users this user follows."""
    q = (
        select(CommunityFollow, User)
        .join(User, User.id == CommunityFollow.followed_id)
        .where(CommunityFollow.follower_id == user_id)
        .order_by(CommunityFollow.created_at.desc())
        .limit(min(limit, 500)).offset(offset)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "user_id": str(u.id),
            "email": u.email,
            "role": u.role,
            "followed_at": f.created_at.isoformat(),
        }
        for f, u in rows
    ]


async def list_followers(
    db: AsyncSession, *, user_id: uuid.UUID,
    limit: int = 100, offset: int = 0,
) -> list[dict[str, Any]]:
    """Users who follow this user."""
    q = (
        select(CommunityFollow, User)
        .join(User, User.id == CommunityFollow.follower_id)
        .where(CommunityFollow.followed_id == user_id)
        .order_by(CommunityFollow.created_at.desc())
        .limit(min(limit, 500)).offset(offset)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "user_id": str(u.id),
            "email": u.email,
            "role": u.role,
            "followed_at": f.created_at.isoformat(),
        }
        for f, u in rows
    ]


async def follow_counts(
    db: AsyncSession, *, user_id: uuid.UUID,
) -> dict[str, int]:
    following = int((await db.execute(
        select(func.count()).select_from(CommunityFollow).where(
            CommunityFollow.follower_id == user_id,
        ),
    )).scalar() or 0)
    followers = int((await db.execute(
        select(func.count()).select_from(CommunityFollow).where(
            CommunityFollow.followed_id == user_id,
        ),
    )).scalar() or 0)
    return {"following": following, "followers": followers}


# ------------------------- Feed -------------------------

async def followed_feed(
    db: AsyncSession, *, user_id: uuid.UUID,
    within_hours: int = 168,  # 7 days
    limit: int = 50, offset: int = 0,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Posts from users this user follows, newest first.

    Only approved posts within the window are returned.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=within_hours)

    subq = (
        select(CommunityFollow.followed_id)
        .where(CommunityFollow.follower_id == user_id)
    )
    q = (
        select(CommunityPost, User.email)
        .join(User, User.id == CommunityPost.author_id, isouter=True)
        .where(
            CommunityPost.author_id.in_(subq),
            CommunityPost.moderation_status == "approved",
            CommunityPost.created_at >= since,
        )
        .order_by(CommunityPost.created_at.desc())
        .limit(min(limit, 200)).offset(offset)
    )
    rows = (await db.execute(q)).all()
    out: list[dict[str, Any]] = []
    for p, author_email in rows:
        ca = p.created_at
        if ca is not None and ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        out.append({
            "post_id": str(p.id),
            "title": p.title,
            "tags": p.tags or [],
            "author_id": str(p.author_id) if p.author_id else None,
            "author_email": author_email,
            "like_count": p.like_count,
            "view_count": p.view_count,
            "comment_count": p.comment_count,
            "created_at": ca.isoformat() if ca else None,
        })
    return out


# ------------------------- helpers -------------------------

def _serialize(f: CommunityFollow, *, following: bool) -> dict[str, Any]:
    return {
        "follower_id": str(f.follower_id),
        "followed_id": str(f.followed_id),
        "following": following,
        "followed_at": f.created_at.isoformat() if f.created_at else None,
    }
