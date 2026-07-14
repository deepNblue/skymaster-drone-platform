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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.community import CommunityComment, CommunityPost, CommunityReport
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
