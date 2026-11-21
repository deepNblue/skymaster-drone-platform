"""Community module API endpoints — v2.2 E4 Community.

Implements:
- GET /community/posts — list (public / tenant-scoped)
- POST /community/posts — create new post (auto-moderate via keyword filter)
- GET /community/posts/{id} — get single post + comments
- PUT /community/posts/{id} — update (author-only) → re-moderate
- DELETE /community/posts/{id} — delete (author / admin)
- POST /community/posts/{id}/like — like (idempotent via unique constraint)
- DELETE /community/posts/{id}/like — unlike
- POST /community/posts/{id}/comments — add comment
- GET /community/posts/{id}/comments — list comments (threaded)
- POST /community/reports — report a post/comment
- GET /community/moderation/reports — admin list open reports
- POST /community/moderation/reports/{id}/resolve — resolve report
"""
from __future__ import annotations

import os
from typing import Annotated, Optional, List
from datetime import datetime
from uuid import UUID
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models.community import (
    CommunityPost, CommunityComment, CommunityReport, CommunityLike,
    CommunityAppeal,
)
from app.models.user import User
from app.services.community_moderation import (
    moderate_content, ModerationResult,
)


router = APIRouter(prefix="/community", tags=["community"])


# ---------- Schemas ---------------------------------------------------------

class CommunityPostOut(BaseModel):
    id: UUID
    tenant_id: Optional[UUID]
    author_id: Optional[UUID]
    title: str
    body: str
    tags: Optional[List[str]]
    moderation_status: str
    pinned: bool
    view_count: int
    like_count: int
    comment_count: int
    moderation_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateCommunityPostRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=2)
    tags: Optional[List[str]] = Field(default_factory=list)
    tenant_id: Optional[UUID] = None  # None → public


class UpdateCommunityPostRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    body: Optional[str] = Field(None, min_length=2)
    tags: Optional[List[str]] = None


class CommunityCommentOut(BaseModel):
    id: UUID
    post_id: UUID
    parent_id: Optional[UUID]
    author_id: Optional[UUID]
    body: str
    moderation_status: str
    like_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateCommentRequest(BaseModel):
    body: str = Field(min_length=2)
    parent_id: Optional[UUID] = None


class ReportPostRequest(BaseModel):
    post_id: UUID
    reason: str = Field(min_length=1, max_length=32)
    note: Optional[str] = None


class ResolveReportRequest(BaseModel):
    action: str = Field(description="'resolve' or 'dismiss'")
    note: Optional[str] = None


class PostListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[CommunityPostOut]


# ---------- Helpers ---------------------------------------------------------


def can_moderate(user: User, post: CommunityPost) -> bool:
    """Check if user has permission to moderate this post."""
    if user.role == "admin":
        return True
    if user.role == "system_officer" and (post.tenant_id == user.org_id):
        return True
    return False


# ---------- Endpoints -------------------------------------------------------


@router.get("/posts", response_model=PostListResponse)
async def list_posts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: Optional[UUID] = None,
    tag: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostListResponse:
    """List community posts.

    - If tenant_id given: only return posts from that tenant (user must be member)
    - If tenant_id omitted: return public posts only
    - Only returns approved/pinned posts; pending/rejected are only visible to author/mod
    """
    offset = (page - 1) * size
    # Base query: filter by tenant + approved/pinned
    query = select(CommunityPost).order_by(
        CommunityPost.pinned.desc(),
        desc(CommunityPost.created_at),
    )

    # Tenant visibility
    if tenant_id is not None:
        # Must be authenticated in that org to see private posts
        if current_user is None or current_user.org_id != tenant_id:
            raise HTTPException(403, "not permitted to view this tenant's community")
        query = query.where(CommunityPost.tenant_id == tenant_id)
    else:
        # Public only
        query = query.where(CommunityPost.tenant_id.is_(None))

    # Non-authors only see approved + pinned
    if current_user is None:
        query = query.where(
            (CommunityPost.moderation_status == "approved")
            | (CommunityPost.pinned == True)
        )
    elif current_user.role != "admin" and current_user.role != "system_officer":
        # Regular user can see their own pending/rejected
        query = query.where(
            (CommunityPost.moderation_status == "approved")
            | (CommunityPost.author_id == current_user.id)
            | (CommunityPost.pinned == True)
        )

    if tag is not None:
        # JSONB contains tag — dialect-specific, works on Postgres
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        query = query.where(cast(CommunityPost.tags, JSONB).contains([tag]))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Fetch page
    query = query.offset(offset).limit(size).options(selectinload(CommunityPost.comments))
    result = await db.execute(query)
    posts = result.scalars().all()

    items = [
        CommunityPostOut.model_validate(p)
        for p in posts
    ]
    return PostListResponse(
        total=total,
        page=page,
        size=size,
        items=items,
    )


@router.post("/posts", response_model=CommunityPostOut, status_code=201)
async def create_post(
    req: CreateCommunityPostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityPostOut:
    """Create a new community post. Runs content through keyword moderation."""
    # Tenant permissions: user can only post to their own org or public
    if req.tenant_id is not None:
        if current_user.org_id != req.tenant_id:
            raise HTTPException(403, "cannot post to another organization's community")

    # Run moderation
    full_text = f"{req.title}\n\n{req.body}"
    result: ModerationResult = moderate_content(full_text)

    post = CommunityPost(
        tenant_id=req.tenant_id,
        author_id=current_user.id,
        title=req.title,
        body=req.body,
        tags=req.tags,
        moderation_status=result.status,
        moderation_reason=result.reason,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return CommunityPostOut.model_validate(post)


# ---------- T6.20: /posts/mine (must be before /posts/{post_id}) -----------

@router.get("/posts/mine")
async def list_my_posts(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's own posts (all statuses)."""
    valid_statuses = {"approved", "pending", "rejected", "auto_hidden", "archived"}
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(400, f"Invalid status_filter: {status_filter}")

    q = select(CommunityPost).where(CommunityPost.author_id == current_user.id)
    if status_filter:
        q = q.where(CommunityPost.moderation_status == status_filter)
    q = q.order_by(desc(CommunityPost.created_at)).limit(limit).offset(offset)
    posts = (await db.execute(q)).scalars().all()
    return {"items": [CommunityPostOut.model_validate(p).model_dump(mode="json") for p in posts]}


# ---------- T6.19: /posts/trending (must be before /posts/{post_id}) -------

@router.get("/posts/trending")
async def list_trending_posts(
    within_hours: int = Query(24, alias="window_hours"),
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trending posts ordered by hotness = 2*likes + 1*comments."""
    cutoff = datetime.utcnow() - timedelta(hours=within_hours)
    q = (
        select(CommunityPost)
        .where(
            CommunityPost.moderation_status == "approved",
            CommunityPost.pinned == False,  # noqa: E712
            CommunityPost.created_at >= cutoff,
        )
        .order_by(
            desc(2 * CommunityPost.like_count + CommunityPost.comment_count),
            desc(CommunityPost.created_at),
        )
        .limit(limit)
    )
    posts = (await db.execute(q)).scalars().all()
    return {"items": [CommunityPostOut.model_validate(p).model_dump(mode="json") for p in posts]}


@router.get("/posts/{post_id}", response_model=CommunityPostOut)
async def get_post(
    post_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityPostOut:
    """Get a single post by ID. Increment view_count on fetch."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    # Visibility check
    if post.moderation_status != "approved" and not post.pinned:
        if current_user is None:
            raise HTTPException(403, "not permitted")
        if current_user.id != post.author_id and not can_moderate(current_user, post):
            raise HTTPException(403, "not permitted")

    # Increment view count
    post.view_count += 1
    await db.commit()
    await db.refresh(post)
    return CommunityPostOut.model_validate(post)


@router.put("/posts/{post_id}", response_model=CommunityPostOut)
async def update_post(
    post_id: UUID,
    req: UpdateCommunityPostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityPostOut:
    """Update an existing post (author-only). Re-runs moderation."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    if post.author_id != current_user.id and not can_moderate(current_user, post):
        raise HTTPException(403, "not permitted to update this post")

    if req.title is not None:
        post.title = req.title
    if req.body is not None:
        post.body = req.body
    if req.tags is not None:
        post.tags = req.tags

    # Re-moderate
    full_text = f"{post.title}\n\n{post.body}"
    result = moderate_content(full_text)
    post.moderation_status = result.status
    post.moderation_reason = result.reason

    await db.commit()
    await db.refresh(post)
    return CommunityPostOut.model_validate(post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a post (author or mod). Cascades to comments/likes/reports."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    if post.author_id != current_user.id and not can_moderate(current_user, post):
        raise HTTPException(403, "not permitted to delete this post")

    await db.delete(post)
    await db.commit()

    return {"detail": "deleted"}


@router.post("/posts/{post_id}/like", status_code=200)
async def like_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Like a post. Idempotent: inserting duplicate does nothing (unique constraint)."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    # Check if already liked
    existing = (
        await db.execute(
            select(CommunityLike).where(
                CommunityLike.post_id == post_id,
                CommunityLike.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Already liked — just return current count
        return {"like_count": post.like_count, "liked_by_me": True}

    like = CommunityLike(post_id=post_id, user_id=current_user.id)
    db.add(like)
    post.like_count += 1
    await db.commit()
    return {"like_count": post.like_count, "liked_by_me": True}


@router.delete("/posts/{post_id}/like", status_code=200)
async def unlike_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unlike a previously liked post."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    existing = (
        await db.execute(
            select(CommunityLike).where(
                CommunityLike.post_id == post_id,
                CommunityLike.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return {"like_count": post.like_count, "liked_by_me": False}

    await db.delete(existing)
    if post.like_count > 0:
        post.like_count -= 1
    await db.commit()
    return {"like_count": post.like_count, "liked_by_me": False}


@router.post("/posts/{post_id}/comments", response_model=CommunityCommentOut, status_code=201)
async def add_comment(
    post_id: UUID,
    req: CreateCommentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityCommentOut:
    """Add a comment to a post (supports threaded replies via parent_id)."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    if post.moderation_status != "approved" and not post.pinned:
        raise HTTPException(409, "cannot comment on non-approved post")

    if req.parent_id is not None:
        parent = (
            await db.execute(
                select(CommunityComment).where(CommunityComment.id == req.parent_id)
            )
        ).scalar_one_or_none()
        if parent is None or parent.post_id != post_id:
            raise HTTPException(404, "parent comment not found on this post")

    # Moderate comment body
    result = moderate_content(req.body)

    comment = CommunityComment(
        post_id=post_id,
        parent_id=req.parent_id,
        author_id=current_user.id,
        body=req.body,
        moderation_status=result.status,
        moderation_reason=result.reason,
    )
    db.add(comment)
    post.comment_count += 1
    await db.commit()
    await db.refresh(comment)
    return CommunityCommentOut.model_validate(comment)


@router.get("/posts/{post_id}/comments", response_model=list[CommunityCommentOut])
async def list_comments(
    post_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommunityCommentOut]:
    """List all (approved) comments for a post."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    query = (
        select(CommunityComment)
        .where(CommunityComment.post_id == post_id)
        .order_by(CommunityComment.created_at.asc())
    )

    if current_user is None:
        query = query.where(CommunityComment.moderation_status == "approved")
    elif current_user.role != "admin":
        query = query.where(
            (CommunityComment.moderation_status == "approved")
            | (CommunityComment.author_id == current_user.id)
        )

    result = await db.execute(query)
    comments = result.scalars().all()
    return [
        CommunityCommentOut.model_validate(c)
        for c in comments
    ]


@router.post("/reports", status_code=201)
async def submit_report(
    req: ReportPostRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, UUID]:
    """Submit a user report against a post."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == req.post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    report = CommunityReport(
        post_id=req.post_id,
        reporter_id=current_user.id,
        reason=req.reason,
        note=req.note,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return {"report_id": report.id}


@router.get("/moderation/reports")
async def list_open_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
    status: Optional[str] = None,
):
    """Admin/mod: list reports, optionally filtered by status."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    offset = (page - 1) * size
    query = (
        select(
            CommunityReport.id,
            CommunityReport.post_id,
            CommunityReport.reason,
            CommunityReport.note,
            CommunityReport.status,
            CommunityReport.created_at,
        )
    )
    if status:
        query = query.where(CommunityReport.status == status)
    else:
        query = query.where(CommunityReport.status == "open")
    query = query.order_by(desc(CommunityReport.created_at)).offset(offset).limit(size)
    result = await db.execute(query)
    rows = result.all()
    return {
        "items": [
            {
                "id": str(r[0]),
                "post_id": str(r[1]),
                "reason": r[2],
                "note": r[3],
                "status": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    }


@router.post("/moderation/reports/{report_id}/resolve")
async def resolve_report(
    report_id: UUID,
    req: ResolveReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve an open report: set status to resolved/dismissed."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    action_map = {"resolve": "resolved", "dismiss": "dismissed"}
    if req.action not in action_map:
        raise HTTPException(400, "action must be 'resolve' or 'dismiss'")

    report = (
        await db.execute(
            select(CommunityReport).where(CommunityReport.id == report_id)
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(404, "report not found")

    # Cannot resolve twice
    if report.status in ("resolved", "dismissed"):
        raise HTTPException(409, f"Report already {report.status}")

    report.status = action_map[req.action]
    report.resolved_by = current_user.id
    report.resolved_at = datetime.utcnow()
    report.review_note = req.note

    # If resolved (confirmed), demote the post to pending for review
    if req.action == "resolve":
        post = (
            await db.execute(
                select(CommunityPost).where(CommunityPost.id == report.post_id)
            )
        ).scalar_one_or_none()
        if post is not None and post.moderation_status == "approved":
            post.moderation_status = "pending"
            post.moderation_reason = (
                (post.moderation_reason + "; ") if post.moderation_reason else ""
            ) + f"user reported: {report.reason}"

    # If dismissed, check if the post was auto-hidden and should be restored
    if req.action == "dismiss":
        post = (
            await db.execute(
                select(CommunityPost).where(CommunityPost.id == report.post_id)
            )
        ).scalar_one_or_none()
        if post is not None and (post.moderation_reason or "").startswith("auto-hidden:"):
            # Count remaining open reports for this post
            remaining_open = (
                await db.execute(
                    select(func.count()).select_from(CommunityReport).where(
                        CommunityReport.post_id == report.post_id,
                        CommunityReport.status == "open",
                    )
                )
            ).scalar() or 0
            auto_hide_threshold = int(os.environ.get("COMMUNITY_AUTO_HIDE_THRESHOLD", "3"))
            if remaining_open < auto_hide_threshold:
                post.moderation_status = "approved"
                post.moderation_reason = None

    await db.commit()
    return {
        "id": str(report.id),
        "status": report.status,
        "resolved_by": str(report.resolved_by) if report.resolved_by else None,
        "note": report.review_note,
        "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
    }


# ---------- T6.17: /me/reputation ------------------------------------------

class ReputationOut(BaseModel):
    reports_made: int
    resolved: int
    dismissed: int
    open: int
    weight: float
    label: str


@router.get("/me/reputation", response_model=ReputationOut)
async def get_my_reputation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReputationOut:
    """Get current user's reporter reputation score."""
    reports = (
        await db.execute(
            select(CommunityReport).where(
                CommunityReport.reporter_id == current_user.id
            )
        )
    ).scalars().all()

    resolved = sum(1 for r in reports if r.status == "resolved")
    dismissed = sum(1 for r in reports if r.status == "dismissed")
    total = len(reports)

    weight = max(0.3, min(2.0, 1.0 + 0.2 * resolved - 0.2 * dismissed))
    if weight < 0.6:
        label = "suspect"
    elif weight < 1.4:
        label = "neutral"
    else:
        label = "trusted"

    return ReputationOut(
        reports_made=total,
        resolved=resolved,
        dismissed=dismissed,
        open=total - resolved - dismissed,
        weight=round(weight, 2),
        label=label,
    )


# ---------- T6.22: /me/stats ------------------------------------------------

class UserStatsOut(BaseModel):
    posts_total: int
    posts_by_status: dict[str, int]
    posts_approved: int
    posts_pending: int
    posts_rejected: int
    comments_made: int
    likes_given: int
    likes_received: int


@router.get("/me/stats", response_model=UserStatsOut)
async def get_my_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserStatsOut:
    """Get current user's community stats."""
    posts = (
        await db.execute(
            select(CommunityPost).where(CommunityPost.author_id == current_user.id)
        )
    ).scalars().all()

    status_counts: dict[str, int] = {}
    for p in posts:
        status_counts[p.moderation_status] = status_counts.get(p.moderation_status, 0) + 1

    comments_count = (
        await db.execute(
            select(func.count()).select_from(CommunityComment).where(
                CommunityComment.author_id == current_user.id
            )
        )
    ).scalar() or 0

    likes_given = (
        await db.execute(
            select(func.count()).select_from(CommunityLike).where(
                CommunityLike.user_id == current_user.id
            )
        )
    ).scalar() or 0

    # likes_received: likes on posts authored by current user
    my_post_ids = [p.id for p in posts]
    likes_received = 0
    if my_post_ids:
        likes_received = (
            await db.execute(
                select(func.count()).select_from(CommunityLike).where(
                    CommunityLike.post_id.in_(my_post_ids)
                )
            )
        ).scalar() or 0

    return UserStatsOut(
        posts_total=len(posts),
        posts_by_status=status_counts,
        posts_approved=status_counts.get("approved", 0),
        posts_pending=status_counts.get("pending", 0),
        posts_rejected=status_counts.get("rejected", 0),
        comments_made=comments_count,
        likes_given=likes_given,
        likes_received=likes_received,
    )


# ---------- T6.23: /tags ----------------------------------------------------

@router.get("/tags")
async def list_tags(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tag cloud from approved posts only."""
    posts = (
        await db.execute(
            select(CommunityPost.tags).where(CommunityPost.moderation_status == "approved")
        )
    ).scalars().all()

    counts: dict[str, int] = {}
    for tags_json in posts:
        if tags_json:
            for t in tags_json:
                counts[t] = counts.get(t, 0) + 1

    sorted_tags = dict(sorted(counts.items(), key=lambda x: -x[1])[:limit])
    return {"tags": sorted_tags, "total_distinct": len(counts)}


# ---------- T6.10: /posts/{id}/moderate -------------------------------------

class ModerateRequest(BaseModel):
    action: str  # approve | reject | hide
    reason: Optional[str] = None


@router.post("/posts/{post_id}/moderate", response_model=CommunityPostOut)
async def moderate_post(
    post_id: UUID,
    req: ModerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityPostOut:
    """Admin moderates a post: approve/reject/hide."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "hide": "auto_hidden",
    }
    if req.action not in action_map:
        raise HTTPException(400, f"action must be one of: {list(action_map.keys())}")

    post.moderation_status = action_map[req.action]
    if req.reason:
        post.moderation_reason = req.reason
    await db.commit()
    return CommunityPostOut.model_validate(post)


# ---------- T6.9: /posts/{id}/pin -------------------------------------------

class PinRequest(BaseModel):
    pinned: bool


@router.post("/posts/{post_id}/pin", response_model=CommunityPostOut)
async def toggle_pin(
    post_id: UUID,
    req: PinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityPostOut:
    """Admin sets pin state on a post."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    # Only approved posts can be pinned
    if post.moderation_status != "approved":
        raise HTTPException(409, "Only approved posts can be pinned")

    post.pinned = req.pinned
    await db.commit()
    await db.refresh(post)
    return CommunityPostOut.model_validate(post)


# ---------- T6.11: /posts/{id}/report (rate-limited) ------------------------

class ReportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=32)
    detail: Optional[str] = None


@router.post("/posts/{post_id}/report", status_code=201)
async def report_post(
    post_id: UUID,
    req: ReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report a post (one report per user per post, rate-limited, auto-hide)."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    # Self-report check
    if post.author_id == current_user.id:
        raise HTTPException(400, "Cannot report your own post")

    # Check existing report by same reporter on same post
    existing = (
        await db.execute(
            select(CommunityReport).where(
                CommunityReport.post_id == post_id,
                CommunityReport.reporter_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Already reported this post")

    # Rate limit: env-configurable, per-reporter
    rate_max = int(os.environ.get("COMMUNITY_REPORT_RATE_MAX", "5"))
    if rate_max > 0:
        window_hours = int(os.environ.get("COMMUNITY_REPORT_RATE_WINDOW_HOURS", "24"))
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)
        recent_count = (
            await db.execute(
                select(func.count()).select_from(CommunityReport).where(
                    CommunityReport.reporter_id == current_user.id,
                    CommunityReport.created_at >= cutoff,
                )
            )
        ).scalar() or 0
        if recent_count >= rate_max:
            raise HTTPException(429, "Rate limit exceeded: too many reports")

    report = CommunityReport(
        post_id=post_id,
        reporter_id=current_user.id,
        reason=req.reason,
        note=req.detail,
        status="open",
    )
    db.add(report)

    # Auto-hide: when open reports on this post reach threshold
    auto_hide_threshold = int(os.environ.get("COMMUNITY_AUTO_HIDE_THRESHOLD", "3"))
    if auto_hide_threshold > 0:
        # Count unique open reporters (excluding the one we just added)
        open_reporters = (
            await db.execute(
                select(CommunityReport).where(
                    CommunityReport.post_id == post_id,
                    CommunityReport.status == "open",
                )
            )
        ).scalars().all()
        open_count = len(open_reporters) + 1  # +1 for the new report

        weighted = os.environ.get("COMMUNITY_REPORT_WEIGHTED", "0") == "1"
        if weighted:
            # Calculate weighted score: sum of reporter weights
            reporter_ids = set(r.reporter_id for r in open_reporters)
            reporter_ids.add(current_user.id)
            score = 0.0
            for rid in reporter_ids:
                rep_reports = (
                    await db.execute(
                        select(CommunityReport).where(
                            CommunityReport.reporter_id == rid
                        )
                    )
                ).scalars().all()
                rep_resolved = sum(1 for r in rep_reports if r.status == "resolved")
                rep_dismissed = sum(1 for r in rep_reports if r.status == "dismissed")
                rep_weight = max(0.3, min(2.0, 1.0 + 0.2 * rep_resolved - 0.2 * rep_dismissed))
                score += rep_weight
            if score >= auto_hide_threshold:
                post.moderation_status = "pending"
                post.moderation_reason = f"auto-hidden: weighted score={round(score, 1)} ({len(reporter_ids)} reporters)"
        else:
            if open_count >= auto_hide_threshold:
                post.moderation_status = "pending"
                post.moderation_reason = f"auto-hidden: {open_count} open reports"

    await db.commit()
    await db.refresh(report)
    return {
        "id": str(report.id),
        "post_id": str(report.post_id),
        "reporter_id": str(report.reporter_id),
        "reason": report.reason,
        "note": report.note,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


# ---------- T6.16: /posts/{id}/appeal ---------------------------------------

class AppealRequest(BaseModel):
    note: Optional[str] = None


@router.post("/posts/{post_id}/appeal", status_code=201)
async def appeal_post(
    post_id: UUID,
    req: AppealRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Appeal a moderation decision on a post (author only)."""
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    if post.author_id != current_user.id:
        raise HTTPException(403, "Only the author can appeal")

    # Can only appeal posts that are auto-hidden or pending (auto-hide sets status to pending)
    if post.moderation_status not in ("auto_hidden", "pending"):
        raise HTTPException(409, "Can only appeal auto-hidden posts")

    # Check for existing pending appeal
    existing = (
        await db.execute(
            select(CommunityAppeal).where(
                CommunityAppeal.post_id == post_id,
                CommunityAppeal.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "An active appeal already exists for this post")

    appeal = CommunityAppeal(
        post_id=post_id,
        author_id=current_user.id,
        note=req.note,
        status="pending",
    )
    db.add(appeal)
    await db.commit()
    return {"id": str(appeal.id), "status": "pending"}


# ---------- T6.16: /moderation/appeals resolve ------------------------------

class ResolveAppealRequest(BaseModel):
    action: str  # uphold | overturn
    review_note: Optional[str] = None


@router.post("/moderation/appeals/{appeal_id}/resolve")
async def resolve_appeal(
    appeal_id: UUID,
    req: ResolveAppealRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin resolves an appeal: uphold or overturn."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    appeal = (
        await db.execute(
            select(CommunityAppeal).where(CommunityAppeal.id == appeal_id)
        )
    ).scalar_one_or_none()
    if appeal is None:
        raise HTTPException(404, "appeal not found")

    if req.action not in ("uphold", "overturn"):
        raise HTTPException(400, "action must be 'uphold' or 'overturn'")

    # Map action to status string expected by tests
    status_map = {"uphold": "upheld", "overturn": "overturned"}
    appeal.status = status_map[req.action]
    appeal.reviewed_by = current_user.id
    appeal.reviewed_at = datetime.utcnow()
    appeal.review_note = req.review_note

    post = (
        await db.execute(
            select(CommunityPost).where(CommunityPost.id == appeal.post_id)
        )
    ).scalar_one_or_none()
    if post and req.action == "overturn":
        post.moderation_status = "approved"
        post.moderation_reason = None
        # Dismiss reports that triggered the hide
        reports = (
            await db.execute(
                select(CommunityReport).where(
                    CommunityReport.post_id == appeal.post_id,
                    CommunityReport.status == "open",
                )
            )
        ).scalars().all()
        for r in reports:
            r.status = "dismissed"
            r.resolved_by = current_user.id
            r.resolved_at = datetime.utcnow()

    await db.commit()
    return {"status": appeal.status}


# ---------- T6.21: /moderation/reporters/{id}/reputation -------------------

@router.get("/moderation/reporters/{user_id}/reputation", response_model=ReputationOut)
async def get_reporter_reputation(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReputationOut:
    """Admin checks a reporter's reputation (same logic as /me/reputation)."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    reports = (
        await db.execute(
            select(CommunityReport).where(CommunityReport.reporter_id == user_id)
        )
    ).scalars().all()

    resolved = sum(1 for r in reports if r.status == "resolved")
    dismissed = sum(1 for r in reports if r.status == "dismissed")
    total = len(reports)

    weight = max(0.3, min(2.0, 1.0 + 0.2 * resolved - 0.2 * dismissed))
    if weight < 0.6:
        label = "suspect"
    elif weight < 1.4:
        label = "neutral"
    else:
        label = "trusted"

    return ReputationOut(
        reports_made=total,
        resolved=resolved,
        dismissed=dismissed,
        open=total - resolved - dismissed,
        weight=round(weight, 2),
        label=label,
    )


# ---------- T6.24: /moderation/stats ----------------------------------------

class ModerationStatsOut(BaseModel):
    total_reports: int
    open_reports: int
    resolved_reports: int
    dismissed_reports: int
    total_appeals: int
    pending_appeals: int
    overturned_appeals: int
    posts_pending: int
    posts_approved: int
    posts_rejected: int
    posts_auto_hidden: int
    auto_hide_threshold: int
    pending_posts: int
    auto_hidden_posts: int
    top_reasons_7d: list[dict] = []


@router.get("/moderation/stats", response_model=ModerationStatsOut)
async def get_moderation_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModerationStatsOut:
    """Moderation statistics summary."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    reports = (
        await db.execute(select(CommunityReport))
    ).scalars().all()
    appeals = (
        await db.execute(select(CommunityAppeal))
    ).scalars().all()
    posts = (
        await db.execute(select(CommunityPost))
    ).scalars().all()

    # Top report reasons in last 7 days
    cutoff_7d = datetime.utcnow() - timedelta(days=7)
    recent_reports = [r for r in reports if r.created_at and r.created_at >= cutoff_7d]
    reason_counts: dict[str, int] = {}
    for r in recent_reports:
        reason_counts[r.reason] = reason_counts.get(r.reason, 0) + 1
    top_reasons = sorted(
        [{"reason": k, "count": v} for k, v in reason_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    return ModerationStatsOut(
        total_reports=len(reports),
        open_reports=sum(1 for r in reports if r.status == "open"),
        resolved_reports=sum(1 for r in reports if r.status == "resolved"),
        dismissed_reports=sum(1 for r in reports if r.status == "dismissed"),
        total_appeals=len(appeals),
        pending_appeals=sum(1 for a in appeals if a.status == "pending"),
        overturned_appeals=sum(1 for a in appeals if a.status == "overturned"),
        posts_pending=sum(1 for p in posts if p.moderation_status == "pending"),
        posts_approved=sum(1 for p in posts if p.moderation_status == "approved"),
        posts_rejected=sum(1 for p in posts if p.moderation_status == "rejected"),
        posts_auto_hidden=sum(1 for p in posts if p.moderation_status == "auto_hidden"),
        auto_hide_threshold=int(os.environ.get("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")),
        pending_posts=sum(1 for p in posts if p.moderation_status == "pending"),
        auto_hidden_posts=sum(1 for p in posts if (p.moderation_reason or "").startswith("auto-hidden:")),
        top_reasons_7d=top_reasons,
    )
