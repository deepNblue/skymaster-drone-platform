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
    ModelDeployment, ModelListing, ModelUsageEvent, ModelVersion,
)
from app.models.user import User
from app.schemas.model_marketplace import (
    DeploymentCreate, DeploymentOut,
    ListingCreate, ListingOut, ListingPage,
    UsageRecord, UsageSummary,
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

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()
    stmt = stmt.order_by(
        ModelListing.is_featured.desc(),
        ModelListing.updated_at.desc(),
    ).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return ListingPage(
        total=total, items=[ListingOut.model_validate(r) for r in rows]
    )


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
    return ListingOut.model_validate(listing)


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
