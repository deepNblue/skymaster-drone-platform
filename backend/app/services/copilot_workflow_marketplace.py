"""Copilot Workflow Marketplace service (v2.1 E2.6).

功能:
- publish: 把 org 内的 workflow 冻结为 listing 快照
- unpublish: 软下架 (保留数据不删)
- browse: 分页浏览 public listings (含 org 过滤)
- get_listing: 查看单个 listing 详情
- install: 把 listing 快照克隆为调用者 org 下的新 workflow
- rate: 评分并重算 avg_rating
- list_ratings: 拉取某 listing 的评分
- list_installs_of: 拉取某 listing 的克隆记录 (仅作者可看，用于分析)

Invariants:
- 一个 workflow_id + workflow_version 可发布多次 listing？→ 不允许，同一版本只能发布一次
- 同一 rater 对同一 listing 只能有一条评分 (UniqueConstraint 兜底 + upsert 逻辑)
- 克隆 listing 时按 dsl_yaml_snapshot 重放 parse+validate；如果快照本身无效应报 500 而非 400
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_dsl import (
    WorkflowError,
    parse_workflow,
    validate_workflow,
)
from app.services.tool_registry import build_default_registry
from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_marketplace import (
    CopilotWorkflowInstall,
    CopilotWorkflowListing,
    CopilotWorkflowRating,
)


VALID_VISIBILITY = {"public", "org", "private"}


class MarketplaceError(RuntimeError):
    pass


# ------------------------------------------------------------------
# Publish / Unpublish
# ------------------------------------------------------------------
@dataclass
class PublishRequest:
    workflow_id: UUID
    author_user_id: UUID
    org_id: UUID | None
    title: str
    summary: str
    tags: list[str] | None
    visibility: str = "public"


async def publish_workflow(
    db: AsyncSession, req: PublishRequest,
) -> CopilotWorkflowListing:
    if req.visibility not in VALID_VISIBILITY:
        raise MarketplaceError(f"invalid visibility: {req.visibility}")

    wf_res = await db.execute(
        select(CopilotWorkflow).where(
            and_(
                CopilotWorkflow.id == req.workflow_id,
                CopilotWorkflow.deleted_at.is_(None),
            )
        )
    )
    wf = wf_res.scalar_one_or_none()
    if wf is None:
        raise MarketplaceError("workflow not found or deleted")

    # Ownership check: only workflow author (or same-org member for org listings)
    if wf.owner_user_id and wf.owner_user_id != req.author_user_id:
        # Allow same-org publish when org matches (团队成员帮同事发布)
        if wf.org_id != req.org_id:
            raise MarketplaceError("not authorized to publish this workflow")

    # Duplicate check: same (workflow_id, workflow_version) alive listing
    dup = await db.execute(
        select(CopilotWorkflowListing).where(
            and_(
                CopilotWorkflowListing.workflow_id == req.workflow_id,
                CopilotWorkflowListing.workflow_version == wf.version,
                CopilotWorkflowListing.unpublished_at.is_(None),
            )
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise MarketplaceError(
            f"workflow version {wf.version} already published; "
            "bump the workflow version first"
        )

    listing = CopilotWorkflowListing(
        id=uuid4(),
        workflow_id=wf.id,
        workflow_version=wf.version,
        org_id=req.org_id,
        author_user_id=req.author_user_id,
        title=req.title.strip() or wf.name,
        summary=req.summary.strip(),
        tags=req.tags,
        dsl_yaml_snapshot=wf.dsl_yaml,
        visibility=req.visibility,
        install_count=0,
        avg_rating=0.0,
        rating_count=0,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return listing


async def unpublish_listing(
    db: AsyncSession, *, listing_id: UUID, actor_user_id: UUID, actor_org_id: UUID | None,
) -> None:
    res = await db.execute(
        select(CopilotWorkflowListing).where(CopilotWorkflowListing.id == listing_id)
    )
    listing = res.scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")
    if listing.unpublished_at is not None:
        return  # already unpublished, idempotent

    # Ownership: original author OR same-org admin (last resort — we don't have
    # a proper role check here yet; err on the strict side)
    if listing.author_user_id != actor_user_id:
        if listing.org_id != actor_org_id:
            raise MarketplaceError("not authorized to unpublish")

    listing.unpublished_at = datetime.now(timezone.utc)
    await db.commit()


# ------------------------------------------------------------------
# Browse / Read
# ------------------------------------------------------------------
async def browse_listings(
    db: AsyncSession,
    *,
    viewer_org_id: UUID | None,
    query: str | None = None,
    tag: str | None = None,
    order_by: str = "install_count",  # install_count | avg_rating | published_at
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[CopilotWorkflowListing], int]:
    """List alive listings visible to the viewer.

    Visibility rules:
      - visibility == "public"  → everyone sees
      - visibility == "org"     → same-org members see
      - visibility == "private" → hidden (only via direct id fetch)
    """
    stmt = select(CopilotWorkflowListing).where(
        CopilotWorkflowListing.unpublished_at.is_(None),
    )
    # Visibility clause
    from sqlalchemy import or_
    stmt = stmt.where(
        or_(
            CopilotWorkflowListing.visibility == "public",
            and_(
                CopilotWorkflowListing.visibility == "org",
                CopilotWorkflowListing.org_id == viewer_org_id,
            ),
        )
    )
    if query:
        q = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                CopilotWorkflowListing.title.ilike(q),
                CopilotWorkflowListing.summary.ilike(q),
            )
        )
    if tag:
        # tags is JSONB list — use @> operator on postgres, fallback substr on sqlite
        # Do a Python-side filter after query to stay portable.
        pass

    order_col = {
        "install_count": desc(CopilotWorkflowListing.install_count),
        "avg_rating": desc(CopilotWorkflowListing.avg_rating),
        "published_at": desc(CopilotWorkflowListing.published_at),
    }.get(order_by, desc(CopilotWorkflowListing.install_count))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = stmt.order_by(order_col).limit(limit).offset(offset)
    rows_res = await db.execute(stmt)
    rows = list(rows_res.scalars())

    if tag:
        rows = [r for r in rows if r.tags and tag in r.tags]

    return rows, int(total)


async def get_listing(
    db: AsyncSession, *, listing_id: UUID, viewer_org_id: UUID | None,
) -> CopilotWorkflowListing:
    res = await db.execute(
        select(CopilotWorkflowListing).where(CopilotWorkflowListing.id == listing_id)
    )
    listing = res.scalar_one_or_none()
    if listing is None or listing.unpublished_at is not None:
        raise MarketplaceError("listing not found")

    if listing.visibility == "private":
        raise MarketplaceError("listing not accessible")
    if listing.visibility == "org" and listing.org_id != viewer_org_id:
        raise MarketplaceError("listing not accessible")
    return listing


# ------------------------------------------------------------------
# Install (clone)
# ------------------------------------------------------------------
@dataclass
class InstallResult:
    listing: CopilotWorkflowListing
    new_workflow: CopilotWorkflow
    install: CopilotWorkflowInstall


async def install_listing(
    db: AsyncSession,
    *,
    listing_id: UUID,
    installer_user_id: UUID,
    installer_org_id: UUID | None,
    new_name: str | None = None,
) -> InstallResult:
    listing = await get_listing(
        db, listing_id=listing_id, viewer_org_id=installer_org_id,
    )
    # Re-validate the snapshot to protect against corrupt data
    try:
        doc = parse_workflow(listing.dsl_yaml_snapshot)
        validate_workflow(doc, build_default_registry())
    except WorkflowError as e:
        raise MarketplaceError(
            f"listing snapshot is invalid, cannot install: {type(e).__name__}"
        ) from e

    # Compose a unique name in target org
    base_name = new_name or listing.title
    name = base_name
    n = 1
    while True:
        exists = await db.execute(
            select(CopilotWorkflow.id).where(
                and_(
                    CopilotWorkflow.org_id == installer_org_id,
                    CopilotWorkflow.name == name,
                    CopilotWorkflow.deleted_at.is_(None),
                )
            )
        )
        if exists.first() is None:
            break
        n += 1
        name = f"{base_name} ({n})"
        if n > 50:
            raise MarketplaceError("too many name collisions; try a custom name")

    new_wf = CopilotWorkflow(
        id=uuid4(),
        org_id=installer_org_id,
        owner_user_id=installer_user_id,
        name=name,
        description=(listing.summary or "")[:1024],
        dsl_yaml=listing.dsl_yaml_snapshot,
        version=1,
    )
    db.add(new_wf)

    install = CopilotWorkflowInstall(
        id=uuid4(),
        listing_id=listing.id,
        installer_user_id=installer_user_id,
        installer_org_id=installer_org_id,
        new_workflow_id=new_wf.id,
    )
    db.add(install)

    # Bump listing counter
    listing.install_count = (listing.install_count or 0) + 1
    await db.commit()
    await db.refresh(new_wf)
    await db.refresh(install)
    await db.refresh(listing)

    return InstallResult(listing=listing, new_workflow=new_wf, install=install)


# ------------------------------------------------------------------
# Ratings
# ------------------------------------------------------------------
async def rate_listing(
    db: AsyncSession,
    *,
    listing_id: UUID,
    rater_user_id: UUID,
    rater_org_id: UUID | None,
    stars: int,
    comment: str | None = None,
) -> CopilotWorkflowRating:
    if stars < 1 or stars > 5:
        raise MarketplaceError("stars must be 1..5")

    listing = await get_listing(
        db, listing_id=listing_id, viewer_org_id=rater_org_id,
    )
    # No self-rating
    if listing.author_user_id == rater_user_id:
        raise MarketplaceError("cannot rate your own listing")

    # Upsert
    existing_res = await db.execute(
        select(CopilotWorkflowRating).where(
            and_(
                CopilotWorkflowRating.listing_id == listing_id,
                CopilotWorkflowRating.rater_user_id == rater_user_id,
            )
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing is None:
        row = CopilotWorkflowRating(
            id=uuid4(),
            listing_id=listing_id,
            rater_user_id=rater_user_id,
            rater_org_id=rater_org_id,
            stars=stars,
            comment=comment,
        )
        db.add(row)
    else:
        existing.stars = stars
        existing.comment = comment
        existing.updated_at = datetime.now(timezone.utc)
        row = existing

    # Flush the pending change so aggregate reflects it.
    await db.flush()
    agg_res = await db.execute(
        select(
            func.avg(CopilotWorkflowRating.stars),
            func.count(CopilotWorkflowRating.id),
        ).where(CopilotWorkflowRating.listing_id == listing_id)
    )
    avg, count = agg_res.one()
    listing.avg_rating = float(avg) if avg is not None else 0.0
    listing.rating_count = int(count or 0)

    await db.commit()
    await db.refresh(row)
    await db.refresh(listing)
    return row


async def list_ratings(
    db: AsyncSession, *, listing_id: UUID, limit: int = 20, offset: int = 0,
) -> list[CopilotWorkflowRating]:
    res = await db.execute(
        select(CopilotWorkflowRating)
        .where(CopilotWorkflowRating.listing_id == listing_id)
        .order_by(desc(CopilotWorkflowRating.updated_at))
        .limit(limit).offset(offset)
    )
    return list(res.scalars())


async def get_my_rating(
    db: AsyncSession, *, listing_id: UUID, rater_user_id: UUID,
) -> CopilotWorkflowRating | None:
    res = await db.execute(
        select(CopilotWorkflowRating).where(
            and_(
                CopilotWorkflowRating.listing_id == listing_id,
                CopilotWorkflowRating.rater_user_id == rater_user_id,
            )
        )
    )
    return res.scalar_one_or_none()


# ------------------------------------------------------------------
# Author-only analytics
# ------------------------------------------------------------------
async def list_installs_of(
    db: AsyncSession, *, listing_id: UUID, actor_user_id: UUID,
) -> list[CopilotWorkflowInstall]:
    listing_res = await db.execute(
        select(CopilotWorkflowListing).where(CopilotWorkflowListing.id == listing_id)
    )
    listing = listing_res.scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")
    if listing.author_user_id != actor_user_id:
        raise MarketplaceError("not authorized")

    res = await db.execute(
        select(CopilotWorkflowInstall)
        .where(CopilotWorkflowInstall.listing_id == listing_id)
        .order_by(desc(CopilotWorkflowInstall.installed_at))
    )
    return list(res.scalars())


def listing_to_dict(listing: CopilotWorkflowListing) -> dict[str, Any]:
    return {
        "id": str(listing.id),
        "workflow_id": str(listing.workflow_id),
        "workflow_version": listing.workflow_version,
        "org_id": str(listing.org_id) if listing.org_id else None,
        "author_user_id": str(listing.author_user_id) if listing.author_user_id else None,
        "title": listing.title,
        "summary": listing.summary,
        "tags": listing.tags,
        "visibility": listing.visibility,
        "install_count": listing.install_count,
        "avg_rating": round(float(listing.avg_rating or 0.0), 2),
        "rating_count": listing.rating_count,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
    }


def rating_to_dict(row: CopilotWorkflowRating) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "listing_id": str(row.listing_id),
        "rater_user_id": str(row.rater_user_id),
        "stars": row.stars,
        "comment": row.comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
