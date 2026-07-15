"""Model Marketplace API — v2.0 §3.16.

Endpoints
---------
POST   /api/v1/model-marketplace/listings                         create listing
GET    /api/v1/model-marketplace/listings                         list (filters)
GET    /api/v1/model-marketplace/listings/{lid}                   detail
POST   /api/v1/model-marketplace/listings/{lid}/versions          new version (pending review)
GET    /api/v1/model-marketplace/listings/{lid}/versions          list versions
POST   /api/v1/model-marketplace/versions/{vid}/review            admin: approve/reject/withdraw
POST   /api/v1/model-marketplace/versions/{vid}/install           tenant install → deployment
GET    /api/v1/model-marketplace/deployments                      list my org's deployments
POST   /api/v1/model-marketplace/deployments/{did}/usage          record usage event
GET    /api/v1/model-marketplace/deployments/{did}/usage-summary  quota rollup

Design decisions
* Anyone can browse public listings; the version list only shows
  approved versions to non-owners (owner + admin see everything).
* Only listing owner or admin can push versions; new versions
  land in review_status='pending' and require admin approval
  before non-owners can install.
* Install is org-scoped: one deployment per (org_id, version_id).
* Quota check is best-effort: record_usage() returns 429 if the
  daily rollup would exceed the deployment's quota_calls_per_day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.model_marketplace import (
    ModelDeployment, ModelFavorite, ModelListing, ModelListingReview,
    ModelUsageEvent, ModelVersion,
)
from app.models.user import User
from app.schemas.model_marketplace import (
    DeploymentCreate, DeploymentOut,
    ListingCreate, ListingOut, ListingPage,
    ReviewAggregate, ReviewCreate, ReviewOut,
    UsageDailyPoint, UsageDailySeries, UsageRecord, UsageSummary,
    VersionCreate, VersionOut, VersionReview,
)

router = APIRouter(prefix="/model-marketplace", tags=["model-marketplace"])


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="admin only")


def _is_owner_or_admin(user: User, listing: ModelListing) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    org_id = getattr(user, "org_id", None)
    if listing.owner_user_id and listing.owner_user_id == user.id:
        return True
    if listing.owner_org_id and org_id and listing.owner_org_id == org_id:
        return True
    return False


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------
@router.post("/listings", response_model=ListingOut, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: ListingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingOut:
    # slug uniqueness pre-check for a friendly error.
    dup = (await db.execute(
        select(ModelListing).where(ModelListing.slug == payload.slug)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="slug already exists")
    listing = ModelListing(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        task=payload.task,
        framework=payload.framework,
        tags=payload.tags or [],
        visibility=payload.visibility,
        owner_org_id=getattr(user, "org_id", None),
        owner_user_id=user.id,
        license=payload.license,
        price_model=payload.price_model,
        price_unit=payload.price_unit,
        currency=payload.currency,
    )
    db.add(listing)
    await db.commit()
    return ListingOut.model_validate(listing)


@router.get("/listings", response_model=ListingPage)
async def list_listings(
    task: str | None = Query(None),
    framework: str | None = Query(None),
    tag: str | None = Query(None),
    # T5.12 — search + sort
    q: str | None = Query(
        None, min_length=1, max_length=100,
        description="Case-insensitive substring match on name/description",
    ),
    sort: str = Query(
        "featured",
        description="featured | newest | popular | top_rated",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingPage:
    org_id = getattr(user, "org_id", None)
    stmt = select(ModelListing)
    # Visibility rules:
    #   public  → visible to all
    #   org     → visible only to owner_org_id members
    #   private → visible only to owner_user_id (or admin)
    is_admin = getattr(user, "role", None) == "admin"
    if not is_admin:
        vis_filter = (ModelListing.visibility == "public")
        if org_id is not None:
            vis_filter = vis_filter | (
                (ModelListing.visibility == "org")
                & (ModelListing.owner_org_id == org_id)
            )
        vis_filter = vis_filter | (
            (ModelListing.visibility == "private")
            & (ModelListing.owner_user_id == user.id)
        )
        stmt = stmt.where(vis_filter)
    if task:
        stmt = stmt.where(ModelListing.task == task)
    if framework:
        stmt = stmt.where(ModelListing.framework == framework)
    if tag:
        stmt = stmt.where(ModelListing.tags.contains([tag]))
    # T5.12 — free-text substring search on name + description
    if q:
        needle = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(ModelListing.name).like(needle)
            | func.lower(ModelListing.description).like(needle)
        )

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()
    # T5.12 — sort presets
    if sort == "newest":
        stmt = stmt.order_by(ModelListing.created_at.desc())
    elif sort == "popular":
        # Order by deployment_count DESC via correlated aggregate. SQLite
        # + PG both handle this pattern; for perf on huge datasets we'd
        # cache the count on the listing row, but that's premature here.
        dep_expr = (
            select(func.count(ModelDeployment.id))
            .join(ModelVersion, ModelVersion.id == ModelDeployment.version_id)
            .where(
                ModelVersion.listing_id == ModelListing.id,
                ModelDeployment.status.in_(["installed", "active"]),
            )
            .correlate(ModelListing)
            .scalar_subquery()
        )
        stmt = stmt.order_by(dep_expr.desc(), ModelListing.updated_at.desc())
    elif sort == "top_rated":
        avg_expr = (
            select(func.avg(ModelListingReview.rating))
            .where(ModelListingReview.listing_id == ModelListing.id)
            .correlate(ModelListing)
            .scalar_subquery()
        )
        cnt_expr = (
            select(func.count(ModelListingReview.id))
            .where(ModelListingReview.listing_id == ModelListing.id)
            .correlate(ModelListing)
            .scalar_subquery()
        )
        # Ratings with only 1-2 reviews are noisy — order review_count>=3
        # ahead of the long tail, then avg rating, then updated_at.
        stmt = stmt.order_by(
            (cnt_expr >= 3).desc(),
            avg_expr.desc().nullslast(),
            ModelListing.updated_at.desc(),
        )
    else:  # 'featured' (default)
        stmt = stmt.order_by(
            ModelListing.is_featured.desc(),
            ModelListing.updated_at.desc(),
        )
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    # T5.9 — batch-fetch deployment + version counts for this page in
    # two aggregate queries (no N+1). deployment_count only counts
    # active/installed statuses.
    from app.models.model_marketplace import ModelDeployment, ModelVersion

    listing_ids = [r.id for r in rows]
    dep_counts: dict = {}
    ver_counts: dict = {}
    if listing_ids:
        dep_rows = (await db.execute(
            select(
                ModelVersion.listing_id, func.count(ModelDeployment.id),
            )
            .join(
                ModelVersion,
                ModelVersion.id == ModelDeployment.version_id,
            )
            .where(
                ModelVersion.listing_id.in_(listing_ids),
                ModelDeployment.status.in_(["installed", "active"]),
            )
            .group_by(ModelVersion.listing_id)
        )).all()
        dep_counts = {lid: n for lid, n in dep_rows}

        ver_rows = (await db.execute(
            select(ModelVersion.listing_id, func.count(ModelVersion.id))
            .where(ModelVersion.listing_id.in_(listing_ids))
            .group_by(ModelVersion.listing_id)
        )).all()
        ver_counts = {lid: n for lid, n in ver_rows}

    items = []
    # T5.10 — batch-fetch favorited listing IDs for this caller in one hit
    fav_ids: set = set()
    # T5.11 — batch-fetch review aggregates (avg rating + count) per listing
    rating_map: dict = {}
    if listing_ids:
        fav_rows = (await db.execute(
            select(ModelFavorite.listing_id).where(
                ModelFavorite.user_id == user.id,
                ModelFavorite.listing_id.in_(listing_ids),
            )
        )).all()
        fav_ids = {row[0] for row in fav_rows}
        rating_rows = (await db.execute(
            select(
                ModelListingReview.listing_id,
                func.avg(ModelListingReview.rating),
                func.count(ModelListingReview.id),
            )
            .where(ModelListingReview.listing_id.in_(listing_ids))
            .group_by(ModelListingReview.listing_id)
        )).all()
        rating_map = {
            lid: (float(avg or 0.0), int(cnt)) for lid, avg, cnt in rating_rows
        }
    for r in rows:
        out = ListingOut.model_validate(r)
        out.deployment_count = dep_counts.get(r.id, 0)
        out.version_count = ver_counts.get(r.id, 0)
        out.favorited_by_me = r.id in fav_ids
        avg, cnt = rating_map.get(r.id, (0.0, 0))
        out.average_rating = round(avg, 2)
        out.review_count = cnt
        items.append(out)
    return ListingPage(total=total, items=items)


@router.get("/listings/{lid}", response_model=ListingOut)
async def get_listing(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingOut:
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    if listing.visibility == "private" and listing.owner_user_id != user.id \
       and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=404, detail="listing not found")
    if listing.visibility == "org":
        org_id = getattr(user, "org_id", None)
        if listing.owner_org_id != org_id and getattr(user, "role", None) != "admin":
            raise HTTPException(status_code=404, detail="listing not found")

    # T5.9 — decorate detail response with same aggregates.
    from app.models.model_marketplace import ModelDeployment, ModelVersion

    dep_count = (await db.execute(
        select(func.count(ModelDeployment.id))
        .join(
            ModelVersion,
            ModelVersion.id == ModelDeployment.version_id,
        )
        .where(
            ModelVersion.listing_id == listing.id,
            ModelDeployment.status.in_(["installed", "active"]),
        )
    )).scalar_one()
    ver_count = (await db.execute(
        select(func.count(ModelVersion.id)).where(
            ModelVersion.listing_id == listing.id
        )
    )).scalar_one()
    out = ListingOut.model_validate(listing)
    out.deployment_count = dep_count
    out.version_count = ver_count
    # T5.10 — favorited_by_me
    fav = (await db.execute(
        select(ModelFavorite.id).where(
            ModelFavorite.user_id == user.id,
            ModelFavorite.listing_id == listing.id,
        )
    )).scalar_one_or_none()
    out.favorited_by_me = fav is not None
    # T5.11 — aggregate reviews
    agg = (await db.execute(
        select(
            func.avg(ModelListingReview.rating),
            func.count(ModelListingReview.id),
        ).where(ModelListingReview.listing_id == listing.id)
    )).one()
    avg_val, cnt_val = agg
    out.average_rating = round(float(avg_val or 0.0), 2)
    out.review_count = int(cnt_val or 0)
    return out


# ---------------------------------------------------------------------------
# T5.10 — Favorites (bookmarks)
# ---------------------------------------------------------------------------
@router.post(
    "/listings/{lid}/favorite",
    status_code=status.HTTP_201_CREATED,
)
async def favorite_listing(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Idempotent star. Second call is a no-op that still returns 201."""
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    existing = (await db.execute(
        select(ModelFavorite).where(
            ModelFavorite.user_id == user.id,
            ModelFavorite.listing_id == lid,
        )
    )).scalar_one_or_none()
    if existing:
        return {"favorited": True, "id": str(existing.id)}
    row = ModelFavorite(user_id=user.id, listing_id=lid)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"favorited": True, "id": str(row.id)}


@router.delete("/listings/{lid}/favorite", status_code=status.HTTP_200_OK)
async def unfavorite_listing(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Idempotent unstar. Missing row → 200 with favorited=False."""
    from sqlalchemy import delete
    await db.execute(
        delete(ModelFavorite).where(
            ModelFavorite.user_id == user.id,
            ModelFavorite.listing_id == lid,
        )
    )
    await db.commit()
    return {"favorited": False}


@router.get("/facets")
async def get_marketplace_facets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """T5.13 — facet counts for the filter sidebar.

    Returns per-task, per-framework, and per-tag counts over the
    currently-visible catalog (public visibility). Callers use it to
    populate '(N)' badges next to each filter option and to hide
    filters with 0 rows.

    Three lightweight aggregate queries. If tags growth becomes a
    problem we'll denormalize to a listing_tags junction table.
    """
    # Task counts
    task_rows = (await db.execute(
        select(ModelListing.task, func.count(ModelListing.id))
        .where(ModelListing.visibility == "public")
        .group_by(ModelListing.task)
    )).all()
    tasks = {t: int(c) for t, c in task_rows if t}

    # Framework counts
    fw_rows = (await db.execute(
        select(ModelListing.framework, func.count(ModelListing.id))
        .where(ModelListing.visibility == "public")
        .group_by(ModelListing.framework)
    )).all()
    frameworks = {f: int(c) for f, c in fw_rows if f}

    # Tag counts — expand JSON array to a flat Python counter. Fine at
    # <10k listings; if this becomes a hotspot we switch to a
    # listing_tag junction table + GROUP BY tag_id.
    all_rows = (await db.execute(
        select(ModelListing.tags)
        .where(ModelListing.visibility == "public")
    )).all()
    tag_counts: dict[str, int] = {}
    for (tag_list,) in all_rows:
        for tg in (tag_list or []):
            if not isinstance(tg, str):
                continue
            tag_counts[tg] = tag_counts.get(tg, 0) + 1
    # Top 30 tags — keeps the UI's sidebar bounded
    top_tags = dict(
        sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:30]
    )

    return {
        "tasks": tasks,
        "frameworks": frameworks,
        "tags": top_tags,
        "total": (
            await db.execute(
                select(func.count(ModelListing.id))
                .where(ModelListing.visibility == "public")
            )
        ).scalar_one(),
    }


@router.get("/favorites", response_model=list[ListingOut])
async def list_my_favorites(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ListingOut]:
    """Current user's starred listings — decorated w/ same aggregates."""
    rows = (await db.execute(
        select(ModelListing).join(
            ModelFavorite,
            ModelFavorite.listing_id == ModelListing.id,
        ).where(ModelFavorite.user_id == user.id)
        .order_by(ModelFavorite.created_at.desc())
    )).scalars().all()
    listing_ids = [r.id for r in rows]
    if not listing_ids:
        return []
    dep_rows = (await db.execute(
        select(ModelVersion.listing_id, func.count(ModelDeployment.id))
        .join(ModelVersion, ModelVersion.id == ModelDeployment.version_id)
        .where(
            ModelVersion.listing_id.in_(listing_ids),
            ModelDeployment.status.in_(["installed", "active"]),
        )
        .group_by(ModelVersion.listing_id)
    )).all()
    ver_rows = (await db.execute(
        select(ModelVersion.listing_id, func.count(ModelVersion.id))
        .where(ModelVersion.listing_id.in_(listing_ids))
        .group_by(ModelVersion.listing_id)
    )).all()
    dep_counts = {lid: n for lid, n in dep_rows}
    ver_counts = {lid: n for lid, n in ver_rows}
    out = []
    for r in rows:
        item = ListingOut.model_validate(r)
        item.deployment_count = dep_counts.get(r.id, 0)
        item.version_count = ver_counts.get(r.id, 0)
        item.favorited_by_me = True
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
@router.post(
    "/listings/{lid}/versions",
    response_model=VersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    lid: UUID,
    payload: VersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VersionOut:
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    if not _is_owner_or_admin(user, listing):
        raise HTTPException(status_code=403, detail="not authorized")

    # Duplicate version check.
    dup = (await db.execute(
        select(ModelVersion).where(
            (ModelVersion.listing_id == lid)
            & (ModelVersion.version == payload.version)
        )
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="version already exists")

    version = ModelVersion(
        listing_id=lid,
        version=payload.version,
        artifact_uri=payload.artifact_uri,
        artifact_sha256=payload.artifact_sha256,
        size_bytes=payload.size_bytes,
        inputs_schema=payload.inputs_schema,
        outputs_schema=payload.outputs_schema,
        hardware=payload.hardware or [],
        benchmark=payload.benchmark,
        review_status="pending",
    )
    db.add(version)
    await db.commit()
    return VersionOut.model_validate(version)


@router.get("/listings/{lid}/versions", response_model=list[VersionOut])
async def list_versions(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VersionOut]:
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    stmt = select(ModelVersion).where(ModelVersion.listing_id == lid)
    if not _is_owner_or_admin(user, listing):
        # Non-owners only see approved versions.
        stmt = stmt.where(ModelVersion.review_status == "approved")
    stmt = stmt.order_by(ModelVersion.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [VersionOut.model_validate(r) for r in rows]


@router.post("/versions/{vid}/review", response_model=VersionOut)
async def review_version(
    vid: UUID,
    payload: VersionReview,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VersionOut:
    _require_admin(user)
    ver = (await db.execute(
        select(ModelVersion).where(ModelVersion.id == vid)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="version not found")
    action_map = {
        "approve": "approved",
        "reject": "rejected",
        "withdraw": "withdrawn",
    }
    ver.review_status = action_map[payload.action]
    ver.review_note = payload.note
    ver.reviewer_id = user.id
    ver.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return VersionOut.model_validate(ver)


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------
@router.post(
    "/versions/{vid}/install",
    response_model=DeploymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def install_version(
    vid: UUID,
    payload: DeploymentCreate | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeploymentOut:
    org_id = getattr(user, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=400, detail="user has no org")
    ver = (await db.execute(
        select(ModelVersion).where(ModelVersion.id == vid)
    )).scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="version not found")
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == ver.listing_id)
    )).scalar_one_or_none()
    assert listing is not None  # FK guarantees this
    # Owner/admin may install unapproved versions for internal test.
    if ver.review_status != "approved" and not _is_owner_or_admin(user, listing):
        raise HTTPException(status_code=403, detail="version not approved")

    # Idempotency: one deployment per (org, version).
    existing = (await db.execute(
        select(ModelDeployment).where(
            and_(
                ModelDeployment.org_id == org_id,
                ModelDeployment.version_id == vid,
            )
        )
    )).scalar_one_or_none()
    if existing:
        return DeploymentOut.model_validate(existing)

    dep = ModelDeployment(
        org_id=org_id,
        listing_id=ver.listing_id,
        version_id=vid,
        status="installed",
        endpoint_url=(payload.endpoint_url if payload else None),
        quota_calls_per_day=(payload.quota_calls_per_day if payload else None),
        installed_by=user.id,
    )
    db.add(dep)
    await db.commit()
    return DeploymentOut.model_validate(dep)


@router.get("/deployments", response_model=list[DeploymentOut])
async def list_deployments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeploymentOut]:
    org_id = getattr(user, "org_id", None)
    if org_id is None:
        return []
    rows = (await db.execute(
        select(ModelDeployment)
        .where(ModelDeployment.org_id == org_id)
        .order_by(ModelDeployment.installed_at.desc())
    )).scalars().all()
    return [DeploymentOut.model_validate(r) for r in rows]


@router.post("/deployments/{did}/usage", status_code=status.HTTP_201_CREATED)
async def record_usage(
    did: UUID,
    payload: UsageRecord,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    dep = (await db.execute(
        select(ModelDeployment).where(ModelDeployment.id == did)
    )).scalar_one_or_none()
    if not dep:
        raise HTTPException(status_code=404, detail="deployment not found")
    org_id = getattr(user, "org_id", None)
    if dep.org_id != org_id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="cross-org access forbidden")

    # Quota check — only when quota_calls_per_day is set.
    if dep.quota_calls_per_day:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        used = (await db.execute(
            select(func.coalesce(func.sum(ModelUsageEvent.units), 0)).where(
                and_(
                    ModelUsageEvent.deployment_id == did,
                    ModelUsageEvent.created_at >= since,
                )
            )
        )).scalar_one()
        if int(used) + payload.units > dep.quota_calls_per_day:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"quota exceeded: used {used}, "
                    f"cap {dep.quota_calls_per_day}"
                ),
            )

    event = ModelUsageEvent(
        deployment_id=did,
        units=payload.units,
        unit_type=payload.unit_type,
        latency_ms=payload.latency_ms,
        outcome=payload.outcome,
        meta=payload.meta,
    )
    db.add(event)
    await db.commit()
    return {"ok": True, "recorded_units": payload.units}


@router.get("/deployments/{did}/usage-summary", response_model=UsageSummary)
async def usage_summary(
    did: UUID,
    since_days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageSummary:
    dep = (await db.execute(
        select(ModelDeployment).where(ModelDeployment.id == did)
    )).scalar_one_or_none()
    if not dep:
        raise HTTPException(status_code=404, detail="deployment not found")
    org_id = getattr(user, "org_id", None)
    if dep.org_id != org_id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="cross-org access forbidden")

    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = (await db.execute(
        select(
            ModelUsageEvent.outcome,
            func.coalesce(func.sum(ModelUsageEvent.units), 0),
        )
        .where(
            and_(
                ModelUsageEvent.deployment_id == did,
                ModelUsageEvent.created_at >= since,
            )
        )
        .group_by(ModelUsageEvent.outcome)
    )).all()
    by_outcome = {out: int(total) for out, total in rows}
    return UsageSummary(
        deployment_id=did,
        since_days=since_days,
        total_units=sum(by_outcome.values()),
        by_outcome=by_outcome,
    )


# ---------------------------------------------------------------------------
# T6.6 — daily rollup for the usage dashboard
# ---------------------------------------------------------------------------
@router.get(
    "/deployments/{did}/usage-daily", response_model=UsageDailySeries,
)
async def usage_daily(
    did: UUID,
    since_days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageDailySeries:
    """Daily usage rollup grouped by (day, outcome).

    Backfills missing days with 0 so the frontend can draw a continuous
    line/bar chart without gap handling. UTC-day boundaries.
    """
    dep = (await db.execute(
        select(ModelDeployment).where(ModelDeployment.id == did)
    )).scalar_one_or_none()
    if not dep:
        raise HTTPException(status_code=404, detail="deployment not found")
    org_id = getattr(user, "org_id", None)
    if dep.org_id != org_id and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="cross-org access forbidden")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=since_days)
    # Use func.date to bucket per-day; portable across SQLite + PG.
    day_expr = func.date(ModelUsageEvent.created_at).label("day")
    rows = (await db.execute(
        select(
            day_expr,
            ModelUsageEvent.outcome,
            func.coalesce(func.sum(ModelUsageEvent.units), 0),
        )
        .where(
            and_(
                ModelUsageEvent.deployment_id == did,
                ModelUsageEvent.created_at >= since,
            )
        )
        .group_by(day_expr, ModelUsageEvent.outcome)
    )).all()

    # Fold rows into {day_str: {outcome: units}}.
    buckets: dict[str, dict[str, int]] = {}
    for day, outcome, total in rows:
        day_s = day.isoformat() if hasattr(day, "isoformat") else str(day)
        buckets.setdefault(day_s, {})[outcome] = int(total)

    # Backfill each day in the window so the frontend sees a continuous
    # series (from 'since' up to today, inclusive).
    points: list[UsageDailyPoint] = []
    cursor = since.date()
    end_day = now.date()
    while cursor <= end_day:
        key = cursor.isoformat()
        by_outcome = buckets.get(key, {})
        points.append(UsageDailyPoint(
            day=key,
            total_units=sum(by_outcome.values()),
            by_outcome=by_outcome,
        ))
        cursor = cursor + timedelta(days=1)

    return UsageDailySeries(
        deployment_id=did,
        since_days=since_days,
        quota_calls_per_day=dep.quota_calls_per_day,
        points=points,
    )


# ---------------------------------------------------------------------------
# T5.11 — Reviews
# ---------------------------------------------------------------------------
@router.post(
    "/listings/{lid}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    lid: UUID,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewOut:
    """Create or *upsert* a review. UNIQUE(listing_id, user_id) means a
    second call from the same user updates the existing row rather than
    creating a duplicate — this matches how star-review UX generally
    behaves (edit-my-review, don't spawn N).
    """
    listing = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    existing = (await db.execute(
        select(ModelListingReview).where(
            ModelListingReview.listing_id == lid,
            ModelListingReview.user_id == user.id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        await db.commit()
        await db.refresh(existing)
        return ReviewOut.model_validate(existing)
    row = ModelListingReview(
        listing_id=lid,
        user_id=user.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ReviewOut.model_validate(row)


@router.get("/listings/{lid}/reviews", response_model=list[ReviewOut])
async def list_reviews(
    lid: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReviewOut]:
    rows = (await db.execute(
        select(ModelListingReview)
        .where(ModelListingReview.listing_id == lid)
        .order_by(ModelListingReview.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()
    return [ReviewOut.model_validate(r) for r in rows]


@router.get(
    "/listings/{lid}/reviews/aggregate",
    response_model=ReviewAggregate,
)
async def get_review_aggregate(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewAggregate:
    """Rating histogram + average for a listing.

    Cheap (single GROUP BY rating COUNT query) and used by the detail
    page's review-summary card.
    """
    rows = (await db.execute(
        select(
            ModelListingReview.rating,
            func.count(ModelListingReview.id),
        ).where(ModelListingReview.listing_id == lid)
        .group_by(ModelListingReview.rating)
    )).all()
    histogram: dict[int, int] = {r: 0 for r in range(1, 6)}
    total_score = 0
    total_count = 0
    for rating, cnt in rows:
        histogram[int(rating)] = int(cnt)
        total_score += int(rating) * int(cnt)
        total_count += int(cnt)
    return ReviewAggregate(
        average_rating=round(total_score / total_count, 2) if total_count else 0.0,
        review_count=total_count,
        rating_histogram=histogram,
    )


@router.get(
    "/listings/{lid}/similar",
    response_model=list[ListingOut],
)
async def list_similar_listings(
    lid: UUID,
    limit: int = Query(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ListingOut]:
    """T5.14 — "people also viewed" style recommendations.

    Naive but effective content-based similarity: rank other public
    listings by score =
        +3 if same task
        +2 if same framework
        +1 per shared tag
    Excludes the target listing itself. Cheap for O(N) catalog sizes
    we care about (<10k). For 100k+ we'd move to a vector-embedding
    index (ANN over description text) or the like.
    """
    seed = (await db.execute(
        select(ModelListing).where(ModelListing.id == lid)
    )).scalar_one_or_none()
    if not seed:
        raise HTTPException(status_code=404, detail="listing not found")

    candidates = (await db.execute(
        select(ModelListing).where(
            ModelListing.id != seed.id,
            ModelListing.visibility == "public",
        )
    )).scalars().all()

    seed_tags = set(seed.tags or [])
    scored: list[tuple[int, ModelListing]] = []
    for c in candidates:
        score = 0
        if c.task and c.task == seed.task:
            score += 3
        if c.framework and c.framework == seed.framework:
            score += 2
        shared = seed_tags & set(c.tags or [])
        score += len(shared)
        if score > 0:
            scored.append((score, c))

    scored.sort(
        key=lambda t: (t[0], t[1].updated_at or t[1].created_at),
        reverse=True,
    )
    top = [row for _, row in scored[:limit]]

    if not top:
        return []

    # Backfill deployment_count + review stats in one round each so
    # cards on the detail page look identical to the grid cards.
    listing_ids = [r.id for r in top]
    dep_rows = (await db.execute(
        select(
            ModelVersion.listing_id, func.count(ModelDeployment.id),
        )
        .join(ModelDeployment, ModelDeployment.version_id == ModelVersion.id)
        .where(
            ModelVersion.listing_id.in_(listing_ids),
            ModelDeployment.status.in_(["installed", "active"]),
        )
        .group_by(ModelVersion.listing_id)
    )).all()
    dep_counts = {lid_: int(c) for lid_, c in dep_rows}

    rating_rows = (await db.execute(
        select(
            ModelListingReview.listing_id,
            func.avg(ModelListingReview.rating),
            func.count(ModelListingReview.id),
        )
        .where(ModelListingReview.listing_id.in_(listing_ids))
        .group_by(ModelListingReview.listing_id)
    )).all()
    rating_map = {
        lid_: (float(avg or 0.0), int(cnt)) for lid_, avg, cnt in rating_rows
    }

    out_items: list[ListingOut] = []
    for r in top:
        o = ListingOut.model_validate(r)
        o.deployment_count = dep_counts.get(r.id, 0)
        avg, cnt = rating_map.get(r.id, (0.0, 0))
        o.average_rating = round(avg, 2)
        o.review_count = cnt
        out_items.append(o)
    return out_items


@router.delete(
    "/listings/{lid}/reviews/mine",
    status_code=status.HTTP_200_OK,
)
async def delete_my_review(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Idempotent — missing row still returns 200."""
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(ModelListingReview).where(
            ModelListingReview.listing_id == lid,
            ModelListingReview.user_id == user.id,
        )
    )
    await db.commit()
    return {"deleted": True}
