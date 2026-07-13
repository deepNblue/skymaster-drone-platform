"""Community API — v2.0 §3.18 minimal MVP.

Endpoints
---------
POST   /api/v1/community/posts               create post (moderated)
GET    /api/v1/community/posts               list posts (approved+pinned first)
GET    /api/v1/community/posts/{pid}         post detail + comments
POST   /api/v1/community/posts/{pid}/comments  reply to post
POST   /api/v1/community/posts/{pid}/like    +1 like counter (idempotent-ish)
POST   /api/v1/community/posts/{pid}/moderate  admin: approve/reject/archive
GET    /api/v1/community/moderation/queue    admin: pending posts

Every write path runs `services.community_moderation.moderate_*`. Hits
in the hard-blocked categories short-circuit to `rejected`; spam-only
hits are held `pending` for admin review.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.community import CommunityComment, CommunityPost
from app.models.user import User
from app.schemas.community import (
    CommentCreate,
    CommentOut,
    ModerationDecision,
    PostCreate,
    PostList,
    PostOut,
)
from app.services.community_moderation import moderate_post, moderate_text

router = APIRouter(prefix="/community", tags=["community"])


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="admin only")


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------
@router.post("/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    mod = moderate_post(payload.title, payload.body)
    post = CommunityPost(
        tenant_id=getattr(user, "org_id", None),
        author_id=user.id,
        title=payload.title,
        body=payload.body,
        tags=payload.tags or [],
        moderation_status=mod.status,
        moderation_reason=mod.reason or None,
    )
    db.add(post)
    await db.flush()
    await db.commit()
    return PostOut.model_validate(post)


@router.get("/posts", response_model=PostList)
async def list_posts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(False),
    tag: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostList:
    stmt = select(CommunityPost)
    org_id = getattr(user, "org_id", None)
    # Show public (tenant_id IS NULL) OR own-tenant posts.
    if org_id is not None:
        stmt = stmt.where(
            (CommunityPost.tenant_id.is_(None))
            | (CommunityPost.tenant_id == org_id)
        )
    if include_pending and getattr(user, "role", None) == "admin":
        stmt = stmt.where(
            CommunityPost.moderation_status.in_(["approved", "pending"])
        )
    else:
        stmt = stmt.where(CommunityPost.moderation_status == "approved")
    if tag:
        # JSONB @> filter — fallback to a naive contains via jsonb ops.
        stmt = stmt.where(CommunityPost.tags.contains([tag]))
    stmt_total = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(stmt_total)).scalar_one()
    stmt = stmt.order_by(
        CommunityPost.pinned.desc(),
        CommunityPost.created_at.desc(),
    ).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return PostList(
        total=total,
        items=[PostOut.model_validate(p) for p in rows],
    )


@router.get("/posts/{pid}", response_model=PostOut)
async def get_post(
    pid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    # Tenant guard: rejected posts only visible to author or admin.
    is_admin = getattr(user, "role", None) == "admin"
    if post.moderation_status == "rejected" and not is_admin and post.author_id != user.id:
        raise HTTPException(status_code=404, detail="post not found")
    org_id = getattr(user, "org_id", None)
    if post.tenant_id is not None and org_id is not None and post.tenant_id != org_id and not is_admin:
        raise HTTPException(status_code=404, detail="post not found")
    # Best-effort view counter (non-blocking, race-tolerant).
    post.view_count = (post.view_count or 0) + 1
    await db.commit()
    return PostOut.model_validate(post)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
@router.post(
    "/posts/{pid}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    pid: UUID,
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommentOut:
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post or post.moderation_status != "approved":
        raise HTTPException(status_code=404, detail="post not found")
    mod = moderate_text(payload.body)
    comment = CommunityComment(
        post_id=pid,
        parent_id=payload.parent_id,
        author_id=user.id,
        body=payload.body,
        moderation_status=mod.status,
        moderation_reason=mod.reason or None,
    )
    db.add(comment)
    if mod.status == "approved":
        post.comment_count = (post.comment_count or 0) + 1
    await db.flush()
    await db.commit()
    return CommentOut.model_validate(comment)


@router.get("/posts/{pid}/comments", response_model=list[CommentOut])
async def list_comments(
    pid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommentOut]:
    stmt = (
        select(CommunityComment)
        .where(CommunityComment.post_id == pid)
        .where(CommunityComment.moderation_status == "approved")
        .order_by(CommunityComment.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [CommentOut.model_validate(c) for c in rows]


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------
@router.post("/posts/{pid}/like", response_model=PostOut)
async def like_post(
    pid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post or post.moderation_status != "approved":
        raise HTTPException(status_code=404, detail="post not found")
    post.like_count = (post.like_count or 0) + 1
    await db.commit()
    return PostOut.model_validate(post)


# ---------------------------------------------------------------------------
# Admin — moderation queue + decisions
# ---------------------------------------------------------------------------
@router.get("/moderation/queue", response_model=PostList)
async def moderation_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostList:
    _require_admin(user)
    stmt = select(CommunityPost).where(
        CommunityPost.moderation_status == "pending"
    )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(CommunityPost.created_at.asc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return PostList(total=total, items=[PostOut.model_validate(p) for p in rows])


@router.post("/posts/{pid}/moderate", response_model=PostOut)
async def moderate_decision(
    pid: UUID,
    payload: ModerationDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    _require_admin(user)
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    map_ = {"approve": "approved", "reject": "rejected", "archive": "archived"}
    post.moderation_status = map_[payload.action]
    post.moderation_reason = payload.reason or None
    await db.commit()
    return PostOut.model_validate(post)
