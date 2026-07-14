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

import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.community import CommunityAppeal, CommunityComment, CommunityPost, CommunityReport
from app.models.user import User
from app.schemas.community import (
    CommentCreate,
    CommentOut,
    ModerationDecision,
    PostCreate,
    PostList,
    PostOut,
    ReportCreate,
    ReportList,
    ReportOut,
    ReportResolve,
)
from app.services.community_moderation import moderate_post, moderate_text

router = APIRouter(prefix="/community", tags=["community"])


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="admin only")


# T6.11 — reporter reputation weight.
async def _reporter_weight(db: AsyncSession, reporter_id) -> float:
    """Return a reputation-based weight in [0.3, 2.0] for a reporter.

    Signal source: how admins have historically resolved this reporter's
    reports.
      resolved  → the report was actionable → reputation +1
      dismissed → the report was noise      → reputation −1

    Formula:
      raw   = resolved - dismissed
      weight = clamp(0.3, 1 + 0.2 * raw, 2.0)

    Fresh accounts start at weight=1.0 (no history yet). The ceiling of
    2.0 caps how much a "power reporter" can dominate; the floor of
    0.3 keeps a persistent noise account from being ignored entirely
    (still marginally counted, so a coordinated brigade of them still
    triggers admin review).
    """
    row = (
        await db.execute(
            select(
                func.count().filter(CommunityReport.status == "resolved"),
                func.count().filter(CommunityReport.status == "dismissed"),
            ).where(CommunityReport.reporter_id == reporter_id)
        )
    ).one()
    resolved, dismissed = row
    raw = int(resolved) - int(dismissed)
    return max(0.3, min(2.0, 1.0 + 0.2 * raw))


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

    # T6.17 — bulk-fetch which of these posts the caller has liked,
    # in a single query, then decorate each PostOut. Avoids the N+1
    # round-trip that a per-row lookup would need.
    liked_ids: set[UUID] = set()
    if rows:
        from app.models.community import CommunityLike
        liked_rows = (
            await db.execute(
                select(CommunityLike.post_id).where(
                    CommunityLike.user_id == user.id,
                    CommunityLike.post_id.in_([p.id for p in rows]),
                )
            )
        ).scalars().all()
        liked_ids = set(liked_rows)

    items = []
    for p in rows:
        out = PostOut.model_validate(p)
        out.liked_by_me = p.id in liked_ids
        items.append(out)
    return PostList(total=total, items=items)


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
    # T6.17 — annotate liked_by_me on the single-post detail response.
    from app.models.community import CommunityLike
    liked = (
        await db.execute(
            select(CommunityLike.id).where(
                CommunityLike.post_id == pid,
                CommunityLike.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    out = PostOut.model_validate(post)
    out.liked_by_me = liked is not None
    return out


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
# Reactions — T6.15: idempotent like + real unlike
# ---------------------------------------------------------------------------
@router.post("/posts/{pid}/like", response_model=PostOut)
async def like_post(
    pid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    """Idempotent like: creates a CommunityLike row if absent, bumps
    the denormalized ``like_count`` cache. Repeated calls by the same
    user do NOT inflate the count."""
    from app.models.community import CommunityLike

    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post or post.moderation_status != "approved":
        raise HTTPException(status_code=404, detail="post not found")

    existing = (
        await db.execute(
            select(CommunityLike).where(
                CommunityLike.post_id == pid,
                CommunityLike.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(CommunityLike(post_id=pid, user_id=user.id))
        post.like_count = (post.like_count or 0) + 1
        await db.commit()
    out = PostOut.model_validate(post)
    out.liked_by_me = True
    return out


@router.delete("/posts/{pid}/like", response_model=PostOut)
async def unlike_post(
    pid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    """Idempotent unlike: removes the user's CommunityLike row and
    decrements ``like_count``. If the user hadn't liked, no-op."""
    from app.models.community import CommunityLike

    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post or post.moderation_status != "approved":
        raise HTTPException(status_code=404, detail="post not found")

    existing = (
        await db.execute(
            select(CommunityLike).where(
                CommunityLike.post_id == pid,
                CommunityLike.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        post.like_count = max((post.like_count or 0) - 1, 0)
        await db.commit()
    out = PostOut.model_validate(post)
    out.liked_by_me = False
    return out


# ---------------------------------------------------------------------------
# Admin — moderation queue + decisions
# ---------------------------------------------------------------------------
@router.get("/moderation/stats")
async def moderation_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Admin dashboard summary: open reports, pending posts, auto-hidden
    posts (T6.8). O(3) queries; safe to hit from a polling widget.
    """
    _require_admin(user)
    open_reports = (
        await db.execute(
            select(func.count()).select_from(CommunityReport).where(
                CommunityReport.status == "open"
            )
        )
    ).scalar_one()
    pending_posts = (
        await db.execute(
            select(func.count()).select_from(CommunityPost).where(
                CommunityPost.moderation_status == "pending"
            )
        )
    ).scalar_one()
    auto_hidden = (
        await db.execute(
            select(func.count()).select_from(CommunityPost).where(
                (CommunityPost.moderation_status == "pending")
                & (CommunityPost.moderation_reason.ilike("auto-hidden:%"))
            )
        )
    ).scalar_one()
    threshold = int(os.getenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3"))
    return {
        "open_reports": open_reports,
        "pending_posts": pending_posts,
        "auto_hidden_posts": auto_hidden,
        "auto_hide_threshold": threshold,
    }


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


# ---------------------------------------------------------------------------
# T6.14 — admin pin/unpin
# ---------------------------------------------------------------------------
class PinDecision(BaseModel):
    pinned: bool


@router.post("/posts/{pid}/pin", response_model=PostOut)
async def pin_post(
    pid: UUID,
    payload: PinDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostOut:
    """Admin toggles the pinned flag on a post.

    Pinned posts sort first in the list feed (see list_posts ordering
    on ``CommunityPost.pinned.desc()``). We only allow pinning
    approved posts — pinning something that's still 'pending' or
    'rejected' would show it above the fold before human review,
    which defeats the point of moderation.
    """
    _require_admin(user)
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    if payload.pinned and post.moderation_status != "approved":
        raise HTTPException(
            status_code=409,
            detail="can only pin approved posts",
        )
    post.pinned = bool(payload.pinned)
    await db.commit()
    return PostOut.model_validate(post)


# ---------------------------------------------------------------------------
# T6.16 — author appeal against auto-hide
# ---------------------------------------------------------------------------
class AppealCreate(BaseModel):
    note: str | None = None


class AppealOut(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    post_id: UUID
    author_id: UUID
    note: str | None
    status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class AppealDecision(BaseModel):
    action: str  # 'uphold' | 'overturn'
    review_note: str | None = None


class AppealList(BaseModel):
    items: list[AppealOut]
    total: int


@router.post(
    "/posts/{pid}/appeal",
    response_model=AppealOut,
    status_code=201,
)
async def create_appeal(
    pid: UUID,
    payload: AppealCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealOut:
    """Post author submits an appeal against an auto-hide.

    Preconditions:
      * Post exists.
      * Post is currently 'pending' with an auto-hide reason (i.e. it
        was demoted by T6.8/T6.11, not by a human admin rejecting it).
      * Caller is the post's author.
      * No existing 'pending' appeal for this post (409).
    """
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    if post.author_id != user.id:
        raise HTTPException(
            status_code=403, detail="only the post author can appeal",
        )
    if post.moderation_status != "pending" or not (
        post.moderation_reason or ""
    ).startswith("auto-hidden"):
        raise HTTPException(
            status_code=409,
            detail="post is not currently auto-hidden",
        )
    existing = (
        await db.execute(
            select(CommunityAppeal).where(
                CommunityAppeal.post_id == pid,
                CommunityAppeal.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="a pending appeal already exists",
        )
    appeal = CommunityAppeal(
        post_id=pid,
        author_id=user.id,
        note=payload.note,
        status="pending",
    )
    db.add(appeal)
    await db.commit()
    await db.refresh(appeal)
    return AppealOut.model_validate(appeal)


@router.get("/moderation/appeals", response_model=AppealList)
async def list_appeals(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealList:
    """Admin queue of appeals."""
    _require_admin(user)
    stmt = select(CommunityAppeal).order_by(CommunityAppeal.created_at.desc())
    count_stmt = select(func.count(CommunityAppeal.id))
    if status_filter:
        stmt = stmt.where(CommunityAppeal.status == status_filter)
        count_stmt = count_stmt.where(CommunityAppeal.status == status_filter)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return AppealList(
        items=[AppealOut.model_validate(r) for r in rows],
        total=total,
    )


@router.post(
    "/moderation/appeals/{aid}/resolve",
    response_model=AppealOut,
)
async def resolve_appeal(
    aid: UUID,
    payload: AppealDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealOut:
    """Admin resolves an appeal.

    * uphold → appeal.status='upheld' (keep hidden), no side effects.
    * overturn → appeal.status='overturned':
        - Restore post.moderation_status='approved'
        - Auto-dismiss the open reports on this post (so their reporters
          take a T6.11 rep hit for the false-positive report).
        - Clear moderation_reason.
    """
    from datetime import datetime, timezone

    _require_admin(user)
    if payload.action not in ("uphold", "overturn"):
        raise HTTPException(status_code=422, detail="invalid action")
    appeal = (
        await db.execute(
            select(CommunityAppeal).where(CommunityAppeal.id == aid)
        )
    ).scalar_one_or_none()
    if appeal is None:
        raise HTTPException(status_code=404, detail="appeal not found")
    if appeal.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"appeal already {appeal.status}",
        )
    appeal.reviewed_by = user.id
    appeal.reviewed_at = datetime.now(timezone.utc)
    appeal.review_note = payload.review_note
    if payload.action == "uphold":
        appeal.status = "upheld"
    else:
        appeal.status = "overturned"
        # Restore the post
        post = (
            await db.execute(
                select(CommunityPost).where(CommunityPost.id == appeal.post_id)
            )
        ).scalar_one_or_none()
        if post is not None:
            post.moderation_status = "approved"
            post.moderation_reason = None
        # Auto-dismiss the open reports so their reporters take a rep hit
        open_reports = (
            await db.execute(
                select(CommunityReport).where(
                    CommunityReport.post_id == appeal.post_id,
                    CommunityReport.status == "open",
                )
            )
        ).scalars().all()
        for r in open_reports:
            r.status = "dismissed"
            r.resolved_by = user.id
            r.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(appeal)
    return AppealOut.model_validate(appeal)


# ---------------------------------------------------------------------------
# User-driven reporting (T6.5)
# ---------------------------------------------------------------------------
@router.post(
    "/posts/{pid}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def report_post(
    pid: UUID,
    payload: ReportCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    """Submit a report against a post. One report per (post, reporter).

    A second call by the same reporter returns 409 rather than silently
    dropping — that keeps the UI honest ("you already reported this").
    """
    post = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == pid))
    ).scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    # Don't allow self-report (nice-to-have; avoids trivially clearing
    # your own post from public feeds).
    if post.author_id and post.author_id == user.id:
        raise HTTPException(status_code=400, detail="cannot report your own post")

    dup = (
        await db.execute(
            select(CommunityReport).where(
                (CommunityReport.post_id == pid)
                & (CommunityReport.reporter_id == user.id)
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="already reported")

    # T6.10 — per-reporter rate limit. Same reporter must not file more
    # than N reports across the whole community within a rolling window,
    # to prevent a single bad actor from tanking legitimate posts en
    # masse. Defaults: 5 reports / 24h. Envs override both knobs.
    from datetime import datetime, timedelta, timezone as _tz
    window_hours = int(os.getenv("COMMUNITY_REPORT_RATE_WINDOW_HOURS", "24"))
    window_max = int(os.getenv("COMMUNITY_REPORT_RATE_MAX", "5"))
    if window_max > 0:
        cutoff = datetime.now(tz=_tz.utc) - timedelta(hours=window_hours)
        recent = (
            await db.execute(
                select(func.count()).select_from(CommunityReport).where(
                    (CommunityReport.reporter_id == user.id)
                    & (CommunityReport.created_at >= cutoff)
                )
            )
        ).scalar_one()
        if recent >= window_max:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"report rate limit: {window_max} reports per "
                    f"{window_hours}h — try again later"
                ),
            )

    report = CommunityReport(
        post_id=pid,
        reporter_id=user.id,
        reason=payload.reason,
        note=payload.note,
        status="open",
    )
    db.add(report)
    await db.flush()

    # T6.8 auto-hide: once open-report count crosses AUTO_HIDE_THRESHOLD
    # (default 3), demote an 'approved' post back to 'pending' so it
    # disappears from the public feed until an admin reviews.
    #
    # T6.11 — reputation-weighted variant. Instead of counting each open
    # report as 1.0, we weight it by the reporter's historical accuracy:
    #   weight = clamp(0.3, 1 + 0.2 * (resolved - dismissed), 2.0)
    # so a habitual dismissed-report filer counts less and a reporter
    # whose reports admins keep resolving counts more. Set env var
    # COMMUNITY_REPORT_WEIGHTED=0 to fall back to the old count-based
    # behavior.
    threshold = int(os.getenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3"))
    weighted = os.getenv("COMMUNITY_REPORT_WEIGHTED", "1") != "0"
    if post.moderation_status == "approved":
        open_reports_stmt = select(
            CommunityReport.reporter_id
        ).where(
            (CommunityReport.post_id == pid)
            & (CommunityReport.status == "open")
        )
        open_reporter_ids = (
            await db.execute(open_reports_stmt)
        ).scalars().all()

        if weighted and open_reporter_ids:
            score = 0.0
            for reporter_id in open_reporter_ids:
                score += await _reporter_weight(db, reporter_id)
        else:
            score = float(len(open_reporter_ids))

        if score >= threshold:
            post.moderation_status = "pending"
            post.moderation_reason = (
                f"auto-hidden: {len(open_reporter_ids)} open reports, "
                f"weighted score={score:.2f} (threshold={threshold})"
            )

    await db.commit()
    await db.refresh(report)
    return ReportOut.model_validate(report)


@router.get("/moderation/reports", response_model=ReportList)
async def list_reports(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportList:
    """Admin queue of pending reports."""
    _require_admin(user)
    stmt = select(CommunityReport)
    if status_filter:
        stmt = stmt.where(CommunityReport.status == status_filter)
    else:
        stmt = stmt.where(CommunityReport.status == "open")
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(CommunityReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ReportList(
        total=total,
        items=[ReportOut.model_validate(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# T6.12 — reporter reputation surface for the moderation queue UI
# ---------------------------------------------------------------------------
@router.get("/moderation/reporters/{reporter_id}/reputation")
async def get_reporter_reputation(
    reporter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return one reporter's historical accuracy + current auto-hide weight.

    Admin-only. Used by the moderation queue UI so a reviewer can see
    'this account had 12 resolved + 3 dismissed → weight 2.0' before
    deciding whether to trust a fresh report from them.

    Response shape:
      {
        reporter_id: uuid,
        resolved: int,   # past reports admin found actionable
        dismissed: int,  # past reports admin discarded as noise
        open: int,       # currently open reports from this user
        weight: float,   # T6.11 clamp(0.3, 1 + 0.2*(res-dis), 2.0)
        label: 'trusted' | 'neutral' | 'suspect'
      }
    """
    _require_admin(user)
    row = (
        await db.execute(
            select(
                func.count().filter(CommunityReport.status == "resolved"),
                func.count().filter(CommunityReport.status == "dismissed"),
                func.count().filter(CommunityReport.status == "open"),
            ).where(CommunityReport.reporter_id == reporter_id)
        )
    ).one()
    resolved, dismissed, open_count = row
    weight = await _reporter_weight(db, reporter_id)
    if weight >= 1.4:
        label = "trusted"
    elif weight <= 0.6:
        label = "suspect"
    else:
        label = "neutral"
    return {
        "reporter_id": str(reporter_id),
        "resolved": int(resolved),
        "dismissed": int(dismissed),
        "open": int(open_count),
        "weight": round(weight, 3),
        "label": label,
    }



@router.post(
    "/moderation/reports/{rid}/resolve",
    response_model=ReportOut,
)
async def resolve_report(
    rid: UUID,
    payload: ReportResolve,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    """Admin resolves an open report. Note is appended to report.note."""
    from datetime import datetime, timezone

    _require_admin(user)
    report = (
        await db.execute(
            select(CommunityReport).where(CommunityReport.id == rid)
        )
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    if report.status != "open":
        raise HTTPException(status_code=409, detail="report already resolved")
    report.status = "resolved" if payload.action == "resolve" else "dismissed"
    report.resolved_by = user.id
    report.resolved_at = datetime.now(timezone.utc)
    if payload.note:
        prefix = f"[admin@{user.id}] "
        report.note = (
            f"{report.note}\n{prefix}{payload.note}"
            if report.note else f"{prefix}{payload.note}"
        )

    # T6.8: If resolving the last open report drops the count below the
    # auto-hide threshold, restore the post to 'approved' (only if it
    # was previously auto-hidden — never re-promote admin-rejected content).
    #
    # T6.11 — use the same weighted-score logic as the report path so
    # resolve-based restoration is symmetric with report-based auto-hide.
    threshold = int(os.getenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3"))
    weighted = os.getenv("COMMUNITY_REPORT_WEIGHTED", "1") != "0"
    remaining_ids = (
        await db.execute(
            select(CommunityReport.reporter_id).where(
                (CommunityReport.post_id == report.post_id)
                & (CommunityReport.status == "open")
                & (CommunityReport.id != report.id)
            )
        )
    ).scalars().all()
    if weighted and remaining_ids:
        remaining_score = 0.0
        for rid_ in remaining_ids:
            remaining_score += await _reporter_weight(db, rid_)
    else:
        remaining_score = float(len(remaining_ids))
    if remaining_score < threshold:
        post = (
            await db.execute(
                select(CommunityPost).where(CommunityPost.id == report.post_id)
            )
        ).scalar_one_or_none()
        if (
            post
            and post.moderation_status == "pending"
            and post.moderation_reason
            and post.moderation_reason.startswith("auto-hidden:")
        ):
            post.moderation_status = "approved"
            post.moderation_reason = None

    await db.commit()
    return ReportOut.model_validate(report)
