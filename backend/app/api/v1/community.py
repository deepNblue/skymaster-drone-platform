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

from typing import Annotated, Optional, List
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models.community import (
    CommunityPost, CommunityComment, CommunityReport, CommunityLike,
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
    title: str = Field(min_length=5, max_length=255)
    body: str = Field(min_length=10)
    tags: Optional[List[str]] = Field(default_factory=list)
    tenant_id: Optional[UUID] = None  # None → public


class UpdateCommunityPostRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=5, max_length=255)
    body: Optional[str] = Field(None, min_length=10)
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
    status: str = Field(description="'resolved' or 'dismissed'")
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


@router.post("/posts", response_model=CommunityPostOut)
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


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
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


@router.post("/posts/{post_id}/like", status_code=200)
async def like_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
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
        return {"like_count": post.like_count}

    like = CommunityLike(post_id=post_id, user_id=current_user.id)
    db.add(like)
    post.like_count += 1
    await db.commit()
    return {"like_count": post.like_count}


@router.delete("/posts/{post_id}/like", status_code=200)
async def unlike_post(
    post_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
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
        return {"like_count": post.like_count}

    await db.delete(existing)
    if post.like_count > 0:
        post.like_count -= 1
    await db.commit()
    return {"like_count": post.like_count}


@router.post("/posts/{post_id}/comments", response_model=CommunityCommentOut)
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


@router.get("/moderation/reports", response_model=list[dict])
async def list_open_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
) -> list[dict]:
    """Admin/mod: list all open (unresolved) reports."""
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
        .where(CommunityReport.status == "open")
        .order_by(desc(CommunityReport.created_at))
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(query)
    rows = result.all()
    return [
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


@router.post("/moderation/reports/{report_id}/resolve")
async def resolve_report(
    report_id: UUID,
    req: ResolveReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Resolve an open report: set status to resolved/dismissed, optionally act on post."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    if req.status not in ("resolved", "dismissed"):
        raise HTTPException(400, "status must be 'resolved' or 'dismissed'")

    report = (
        await db.execute(
            select(CommunityReport).where(CommunityReport.id == report_id)
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(404, "report not found")

    report.status = req.status
    report.resolved_by = current_user.id
    from datetime import datetime
    report.resolved_at = datetime.utcnow()
    report.review_note = req.note

    # If resolved, we automatically demote the post back to pending
    # for manual review by another mod.
    if req.status == "resolved":
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

    await db.commit()
    return {"status": "ok"}
