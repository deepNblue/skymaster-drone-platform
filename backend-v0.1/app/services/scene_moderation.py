"""Scene moderation service — v2.1 T2.2.

Report/appeal business logic. Route layer stays thin.

Guardrails encoded here:
* One open report per (listing, user) — repeat calls upsert instead of dupe.
* Auto-hide threshold — when N distinct users have filed open reports of
  category ∈ {copyright, privacy, sensitive_area, illegal}, the listing is
  automatically archived pending admin review. Prevents obvious content
  from staying live for hours while nobody's on call.
* Appeals only allowed on removed listings — you can't appeal an active
  listing. And only the publisher's org can appeal (not the reporter).
* Appeals are single-shot per removal event — appeal_seq monotonically
  increases; you can't reopen a rejected appeal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene_marketplace import SceneListing
from app.models.scene_moderation import (
    APPEAL_STATUSES, REPORT_CATEGORIES, REPORT_STATUSES,
    SceneListingAppeal, SceneListingReport,
)
from app.services import scene_marketplace as market_svc


class ModerationError(Exception):
    pass


# Categories that trigger auto-hide when threshold is reached
AUTO_HIDE_CATEGORIES = {"copyright", "privacy", "sensitive_area", "illegal"}
AUTO_HIDE_THRESHOLD = 3  # distinct users


# ---------------------------------------------------------------------------
# Report — file / list / resolve
# ---------------------------------------------------------------------------


@dataclass
class ReportParams:
    listing_id: UUID
    reporter_user_id: UUID
    reporter_org_id: Optional[UUID]
    category: str
    details: Optional[str] = None


async def file_report(
    db: AsyncSession, params: ReportParams,
) -> tuple[SceneListingReport, bool]:
    """File or update a report. Returns (report, auto_hidden)."""
    if params.category not in REPORT_CATEGORIES:
        raise ModerationError(f"unknown category {params.category!r}")
    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == params.listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise ModerationError("listing not found")

    # Can't report your own listing
    if listing.org_id == params.reporter_org_id:
        raise ModerationError("cannot report your own org's listing")

    # Upsert on (listing, reporter)
    existing = (
        await db.execute(select(SceneListingReport).where(
            SceneListingReport.listing_id == params.listing_id,
            SceneListingReport.reporter_user_id == params.reporter_user_id,
        ))
    ).scalar_one_or_none()

    if existing:
        existing.category = params.category
        existing.details = params.details
        # If it was resolved, reopen it
        if existing.status in ("rejected", "duplicate"):
            existing.status = "open"
            existing.resolver_user_id = None
            existing.resolution_note = None
            existing.resolved_at = None
        report = existing
    else:
        report = SceneListingReport(
            listing_id=params.listing_id,
            reporter_user_id=params.reporter_user_id,
            reporter_org_id=params.reporter_org_id,
            category=params.category,
            details=params.details,
            status="open",
        )
        db.add(report)

    await db.flush()

    # Auto-hide check — count distinct reporters with open reports in
    # auto-hide categories.
    auto_hidden = False
    if listing.status == "active" and params.category in AUTO_HIDE_CATEGORIES:
        count_stmt = (
            select(func.count(func.distinct(SceneListingReport.reporter_user_id)))
            .where(
                SceneListingReport.listing_id == listing.id,
                SceneListingReport.status == "open",
                SceneListingReport.category.in_(list(AUTO_HIDE_CATEGORIES)),
            )
        )
        n = (await db.execute(count_stmt)).scalar_one()
        if int(n or 0) >= AUTO_HIDE_THRESHOLD:
            listing.status = "archived"
            listing.is_featured = False
            auto_hidden = True

    await db.flush()
    return report, auto_hidden


async def list_reports(
    db: AsyncSession, status: Optional[str] = None,
    listing_id: Optional[UUID] = None,
    category: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[SceneListingReport], int]:
    if limit < 1 or limit > 200:
        raise ModerationError("limit must be 1..200")
    conds = []
    if status:
        if status not in REPORT_STATUSES:
            raise ModerationError(f"unknown status {status!r}")
        conds.append(SceneListingReport.status == status)
    if listing_id:
        conds.append(SceneListingReport.listing_id == listing_id)
    if category:
        if category not in REPORT_CATEGORIES:
            raise ModerationError(f"unknown category {category!r}")
        conds.append(SceneListingReport.category == category)

    base = select(SceneListingReport)
    if conds:
        base = base.where(and_(*conds))
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    page = (
        await db.execute(
            base.order_by(SceneListingReport.created_at.desc())
                .limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(page), int(total)


async def report_summary_by_listing(
    db: AsyncSession, listing_id: UUID,
) -> dict:
    """Aggregate counts by (status, category) for a single listing."""
    stmt = (
        select(
            SceneListingReport.status,
            SceneListingReport.category,
            func.count(SceneListingReport.id),
        )
        .where(SceneListingReport.listing_id == listing_id)
        .group_by(SceneListingReport.status, SceneListingReport.category)
    )
    rows = (await db.execute(stmt)).all()
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for status, category, count in rows:
        by_status[status] = by_status.get(status, 0) + int(count)
        by_category[category] = by_category.get(category, 0) + int(count)
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_category": by_category,
    }


async def resolve_report(
    db: AsyncSession, report_id: UUID, resolver_user_id: UUID,
    new_status: str, note: Optional[str] = None,
    take_down_reason: Optional[str] = None,
) -> SceneListingReport:
    """Admin resolves a report.

    * new_status='accepted' with ``take_down_reason`` → automatically
      moderates listing to ``removed`` and marks all other open reports on
      that listing as ``duplicate`` (they belong to the same take-down).
    * new_status='rejected' / 'duplicate' → just closes the row.
    """
    if new_status not in ("reviewing", "accepted", "rejected", "duplicate"):
        raise ModerationError(f"invalid new_status {new_status!r}")
    if new_status == "accepted" and not take_down_reason:
        raise ModerationError("accepted report must supply take_down_reason")

    report = (
        await db.execute(
            select(SceneListingReport).where(SceneListingReport.id == report_id)
        )
    ).scalar_one_or_none()
    if report is None:
        raise ModerationError("report not found")

    report.status = new_status
    report.resolver_user_id = resolver_user_id
    report.resolution_note = note
    report.resolved_at = datetime.now(timezone.utc)
    await db.flush()

    if new_status == "accepted":
        # Take down the listing
        await market_svc.moderate_listing(
            db, report.listing_id, "removed", reason=take_down_reason,
        )
        # Roll up any other open reports on this listing → duplicate
        siblings = (
            await db.execute(select(SceneListingReport).where(
                SceneListingReport.listing_id == report.listing_id,
                SceneListingReport.status == "open",
                SceneListingReport.id != report.id,
            ))
        ).scalars().all()
        for sib in siblings:
            sib.status = "duplicate"
            sib.resolver_user_id = resolver_user_id
            sib.resolution_note = f"rolled up under report {report.id}"
            sib.resolved_at = datetime.now(timezone.utc)
        await db.flush()

    return report


# ---------------------------------------------------------------------------
# Appeal — file / list / resolve / withdraw
# ---------------------------------------------------------------------------


@dataclass
class AppealParams:
    listing_id: UUID
    appellant_user_id: UUID
    appellant_org_id: UUID
    appeal_message: str


async def file_appeal(
    db: AsyncSession, params: AppealParams,
) -> SceneListingAppeal:
    if not params.appeal_message or not params.appeal_message.strip():
        raise ModerationError("appeal_message must be non-empty")
    if len(params.appeal_message) > 4000:
        raise ModerationError("appeal_message too long (>4000 chars)")

    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == params.listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise ModerationError("listing not found")
    if listing.org_id != params.appellant_org_id:
        raise ModerationError("only the publisher's org can appeal")
    if listing.status != "removed":
        raise ModerationError("only removed listings can be appealed")

    # Compute next appeal_seq for this listing
    max_seq = (
        await db.execute(
            select(func.coalesce(func.max(SceneListingAppeal.appeal_seq), 0))
            .where(SceneListingAppeal.listing_id == listing.id)
        )
    ).scalar_one()
    next_seq = int(max_seq or 0) + 1

    # Reject if any pending appeal already exists for this listing
    pending = (
        await db.execute(select(SceneListingAppeal).where(
            SceneListingAppeal.listing_id == listing.id,
            SceneListingAppeal.status == "pending",
        ))
    ).scalar_one_or_none()
    if pending is not None:
        raise ModerationError("a pending appeal already exists for this listing")

    appeal = SceneListingAppeal(
        listing_id=listing.id,
        appeal_seq=next_seq,
        appellant_user_id=params.appellant_user_id,
        original_status=listing.status,
        original_reason=None,
        appeal_message=params.appeal_message.strip(),
        status="pending",
    )
    db.add(appeal)
    await db.flush()
    return appeal


async def resolve_appeal(
    db: AsyncSession, appeal_id: UUID, resolver_user_id: UUID,
    accept: bool, note: Optional[str] = None,
) -> SceneListingAppeal:
    """Accept: restore listing to active. Reject: keep it removed."""
    appeal = (
        await db.execute(
            select(SceneListingAppeal).where(SceneListingAppeal.id == appeal_id)
        )
    ).scalar_one_or_none()
    if appeal is None:
        raise ModerationError("appeal not found")
    if appeal.status != "pending":
        raise ModerationError(f"cannot resolve appeal in status {appeal.status!r}")

    appeal.status = "accepted" if accept else "rejected"
    appeal.resolver_user_id = resolver_user_id
    appeal.resolution_note = note
    appeal.resolved_at = datetime.now(timezone.utc)

    if accept:
        await market_svc.moderate_listing(
            db, appeal.listing_id, "active", reason=None,
        )
    await db.flush()
    return appeal


async def withdraw_appeal(
    db: AsyncSession, appeal_id: UUID, actor_user_id: UUID,
    actor_org_id: UUID,
) -> SceneListingAppeal:
    appeal = (
        await db.execute(
            select(SceneListingAppeal).where(SceneListingAppeal.id == appeal_id)
        )
    ).scalar_one_or_none()
    if appeal is None:
        raise ModerationError("appeal not found")
    if appeal.status != "pending":
        raise ModerationError(f"cannot withdraw appeal in status {appeal.status!r}")

    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == appeal.listing_id))
    ).scalar_one_or_none()
    if listing is None or listing.org_id != actor_org_id:
        raise ModerationError("only the publisher's org can withdraw appeal")

    appeal.status = "withdrawn"
    appeal.resolver_user_id = actor_user_id
    appeal.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return appeal


async def list_appeals(
    db: AsyncSession, status: Optional[str] = None,
    listing_id: Optional[UUID] = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[SceneListingAppeal], int]:
    if limit < 1 or limit > 200:
        raise ModerationError("limit must be 1..200")
    conds = []
    if status:
        if status not in APPEAL_STATUSES:
            raise ModerationError(f"unknown status {status!r}")
        conds.append(SceneListingAppeal.status == status)
    if listing_id:
        conds.append(SceneListingAppeal.listing_id == listing_id)

    base = select(SceneListingAppeal)
    if conds:
        base = base.where(and_(*conds))
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    page = (
        await db.execute(
            base.order_by(SceneListingAppeal.created_at.desc())
                .limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(page), int(total)
