"""F3.4 · Community notification service.

Central inbox for social events: new followers, post likes,
post replies, and mentions. Emit-once/hydrate-many pattern —
producers call `emit_*`, consumers list via `list_for_user`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community_notification import (
    KIND_MENTION, KIND_NEW_FOLLOWER, KIND_POST_LIKED, KIND_POST_REPLY,
    VALID_KINDS, CommunityNotification,
)
from app.models.user import User


class NotificationError(Exception):
    pass


# ------------------------- Emit -------------------------

async def _emit(
    db: AsyncSession, *,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    kind: str,
    post_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    dedupe: bool = True,
) -> CommunityNotification | None:
    """Insert one notification.

    Never notify yourself about your own action (silently drops).
    dedupe=True skips creating duplicate unread notifications for the
    same (recipient, actor, kind, post_id) — collapses rapid retries.
    """
    if kind not in VALID_KINDS:
        raise NotificationError(f"invalid kind: {kind}")
    if actor_id is not None and actor_id == recipient_id:
        return None  # No self-notification.

    if dedupe:
        q = select(CommunityNotification).where(
            CommunityNotification.recipient_id == recipient_id,
            CommunityNotification.actor_id == actor_id,
            CommunityNotification.kind == kind,
            CommunityNotification.post_id == post_id,
            CommunityNotification.read_at.is_(None),
        ).limit(1)
        if (await db.execute(q)).scalar_one_or_none() is not None:
            return None

    n = CommunityNotification(
        recipient_id=recipient_id,
        actor_id=actor_id,
        kind=kind,
        post_id=post_id,
        comment_id=comment_id,
        payload=payload,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n


async def emit_new_follower(
    db: AsyncSession, *,
    followed_id: uuid.UUID, follower_id: uuid.UUID,
) -> CommunityNotification | None:
    return await _emit(
        db,
        recipient_id=followed_id,
        actor_id=follower_id,
        kind=KIND_NEW_FOLLOWER,
    )


async def emit_post_liked(
    db: AsyncSession, *,
    post_author_id: uuid.UUID, liker_id: uuid.UUID,
    post_id: uuid.UUID,
) -> CommunityNotification | None:
    return await _emit(
        db,
        recipient_id=post_author_id,
        actor_id=liker_id,
        kind=KIND_POST_LIKED,
        post_id=post_id,
    )


async def emit_post_reply(
    db: AsyncSession, *,
    post_author_id: uuid.UUID, replier_id: uuid.UUID,
    post_id: uuid.UUID, comment_id: uuid.UUID,
    excerpt: str | None = None,
) -> CommunityNotification | None:
    payload = {"excerpt": excerpt[:200]} if excerpt else None
    return await _emit(
        db,
        recipient_id=post_author_id,
        actor_id=replier_id,
        kind=KIND_POST_REPLY,
        post_id=post_id,
        comment_id=comment_id,
        payload=payload,
        dedupe=False,  # every reply is distinct
    )


async def emit_mention(
    db: AsyncSession, *,
    mentioned_id: uuid.UUID, mentioner_id: uuid.UUID,
    post_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    excerpt: str | None = None,
) -> CommunityNotification | None:
    payload = {"excerpt": excerpt[:200]} if excerpt else None
    return await _emit(
        db,
        recipient_id=mentioned_id,
        actor_id=mentioner_id,
        kind=KIND_MENTION,
        post_id=post_id,
        comment_id=comment_id,
        payload=payload,
        dedupe=False,
    )


# ------------------------- Read -------------------------

async def list_for_user(
    db: AsyncSession, *, user_id: uuid.UUID,
    only_unread: bool = False,
    kinds: list[str] | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    q = select(CommunityNotification, User).where(
        CommunityNotification.recipient_id == user_id,
    ).outerjoin(
        User, User.id == CommunityNotification.actor_id,
    ).order_by(
        CommunityNotification.created_at.desc(),
    ).limit(min(limit, 200)).offset(offset)

    if only_unread:
        q = q.where(CommunityNotification.read_at.is_(None))
    if kinds:
        q = q.where(CommunityNotification.kind.in_(kinds))

    rows = (await db.execute(q)).all()
    return [_serialize(n, actor) for n, actor in rows]


async def unread_count(
    db: AsyncSession, *, user_id: uuid.UUID,
) -> int:
    q = select(func.count()).select_from(
        CommunityNotification,
    ).where(
        CommunityNotification.recipient_id == user_id,
        CommunityNotification.read_at.is_(None),
    )
    return int((await db.execute(q)).scalar() or 0)


async def unread_summary(
    db: AsyncSession, *, user_id: uuid.UUID,
) -> dict[str, int]:
    """Unread count per kind (missing kinds → 0)."""
    q = select(
        CommunityNotification.kind, func.count(),
    ).where(
        CommunityNotification.recipient_id == user_id,
        CommunityNotification.read_at.is_(None),
    ).group_by(CommunityNotification.kind)
    rows = (await db.execute(q)).all()
    out = {k: 0 for k in VALID_KINDS}
    for kind, count in rows:
        out[kind] = int(count)
    out["total"] = sum(out.values())
    return out


# ------------------------- Mutate -------------------------

async def mark_read(
    db: AsyncSession, *, user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> bool:
    """Mark a single notification as read (must belong to user)."""
    now = datetime.now(timezone.utc)
    q = update(CommunityNotification).where(
        CommunityNotification.id == notification_id,
        CommunityNotification.recipient_id == user_id,
        CommunityNotification.read_at.is_(None),
    ).values(read_at=now)
    res = await db.execute(q)
    await db.commit()
    return (res.rowcount or 0) > 0


async def mark_all_read(
    db: AsyncSession, *, user_id: uuid.UUID,
    kinds: list[str] | None = None,
) -> int:
    """Mark all unread notifications as read; returns count updated."""
    now = datetime.now(timezone.utc)
    q = update(CommunityNotification).where(
        CommunityNotification.recipient_id == user_id,
        CommunityNotification.read_at.is_(None),
    ).values(read_at=now)
    if kinds:
        q = q.where(CommunityNotification.kind.in_(kinds))
    res = await db.execute(q)
    await db.commit()
    return int(res.rowcount or 0)


# ------------------------- helpers -------------------------

def _serialize(
    n: CommunityNotification, actor: User | None,
) -> dict[str, Any]:
    ca = n.created_at
    if ca is not None and ca.tzinfo is None:
        ca = ca.replace(tzinfo=timezone.utc)
    ra = n.read_at
    if ra is not None and ra.tzinfo is None:
        ra = ra.replace(tzinfo=timezone.utc)
    return {
        "id": str(n.id),
        "kind": n.kind,
        "actor_id": str(n.actor_id) if n.actor_id else None,
        "actor_email": actor.email if actor else None,
        "post_id": str(n.post_id) if n.post_id else None,
        "comment_id": str(n.comment_id) if n.comment_id else None,
        "payload": n.payload,
        "read_at": ra.isoformat() if ra else None,
        "created_at": ca.isoformat() if ca else None,
        "read": n.read_at is not None,
    }
