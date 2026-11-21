"""Model Marketplace API endpoints - v2.2 E5.

Uses existing ModelListing/ModelVersion/ModelDeployment/ModelUsageEvent/
ModelFavorite/ModelListingReview models.

Endpoints:
- GET  /models                         basic listing (alias of /listings)
- POST /models                         create (auth required)
- GET  /listings                       search + sort
- GET  /listings/{id}                  detail with aggregate counts
- GET  /listings/{id}/similar          similar recommendations
- GET  /facets                         task/framework/tag facets
- POST /listings/{id}/favorite         star
- DEL  /listings/{id}/favorite         unstar
- POST /listings/{id}/reviews          create/upsert review
- GET  /listings/{id}/reviews          list reviews
- GET  /listings/{id}/reviews/aggregate aggregate stats
- DEL  /listings/{id}/reviews/mine     delete my review
- GET  /deployments/{id}/usage-daily   daily usage rollup
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, or_, cast, String as SA_String
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.model_marketplace import (
    ModelListing, ModelVersion, ModelDeployment, ModelUsageEvent,
    ModelFavorite, ModelListingReview,
)
from app.models.user import User

router = APIRouter(prefix="/model-marketplace", tags=["model-marketplace"])


# ---------- Schemas ---------------------------------------------------------

class ListingOut(BaseModel):
    id: UUID
    slug: str
    name: str
    description: Optional[str] = None
    task: str
    framework: str
    tags: Optional[List[str]] = None
    visibility: str
    license: str
    price_model: str
    is_featured: bool
    favorited_by_me: bool = False
    review_count: int = 0
    average_rating: Optional[float] = None
    deployment_count: int = 0
    version_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ListingListResponse(BaseModel):
    total: int
    page: int = 1
    size: int = 20
    items: List[ListingOut]


class FacetsOut(BaseModel):
    tasks: dict[str, int]
    frameworks: dict[str, int]
    tags: dict[str, int]
    total: int


class ReviewOut(BaseModel):
    id: UUID
    listing_id: UUID
    user_id: Optional[UUID] = None
    rating: int
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class CreateReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class ReviewAggregateOut(BaseModel):
    review_count: int
    average_rating: Optional[float]
    rating_histogram: dict[str, int]


class FavoriteOut(BaseModel):
    id: UUID
    favorited: bool


class DailyUsageOut(BaseModel):
    quota_calls_per_day: Optional[int]
    since_days: int
    points: List[dict]


# ---------- Helpers ---------------------------------------------------------

async def _enrich(db: AsyncSession, listing: ModelListing, user_id: Optional[UUID]) -> ListingOut:
    """Build ListingOut with computed fields."""
    # Favorited by me
    fav = False
    if user_id:
        fav_q = await db.execute(
            select(func.count()).select_from(ModelFavorite).where(
                ModelFavorite.listing_id == listing.id,
                ModelFavorite.user_id == user_id,
            )
        )
        fav = (fav_q.scalar() or 0) > 0

    # Review stats
    rev_q = await db.execute(
        select(
            func.count(ModelListingReview.id),
            func.avg(ModelListingReview.rating),
        ).where(ModelListingReview.listing_id == listing.id)
    )
    rev_row = rev_q.one()
    rev_count = int(rev_row[0] or 0)
    avg_rating = float(rev_row[1]) if rev_row[1] is not None else None

    # Deployment count
    dep_q = await db.execute(
        select(func.count()).select_from(ModelDeployment).where(
            ModelDeployment.listing_id == listing.id,
            ModelDeployment.status.in_(["installed", "active"]),
        )
    )
    dep_count = int(dep_q.scalar() or 0)

    # Version count
    ver_q = await db.execute(
        select(func.count()).select_from(ModelVersion).where(
            ModelVersion.listing_id == listing.id
        )
    )
    ver_count = int(ver_q.scalar() or 0)

    return ListingOut(
        id=listing.id,
        slug=listing.slug,
        name=listing.name,
        description=listing.description,
        task=listing.task,
        framework=listing.framework,
        tags=listing.tags or [],
        visibility=listing.visibility,
        license=listing.license,
        price_model=listing.price_model,
        is_featured=listing.is_featured,
        favorited_by_me=fav,
        review_count=rev_count,
        average_rating=round(avg_rating, 2) if avg_rating else None,
        deployment_count=dep_count,
        version_count=ver_count,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


# ---------- GET /models (basic listing) ------------------------------------

@router.get("/models", response_model=ListingListResponse)
async def list_models(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListingListResponse:
    """List public model listings. `category` maps to `task` field."""
    offset = (page - 1) * size
    q = select(ModelListing).where(ModelListing.visibility == "public")
    if category:
        q = q.where(ModelListing.task == category)
    if search:
        term = f"%{search}%"
        q = q.where(or_(
            ModelListing.name.ilike(term),
            ModelListing.description.ilike(term),
        ))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = q.order_by(desc(ModelListing.created_at)).offset(offset).limit(size)
    rows = (await db.execute(q)).scalars().all()

    items = [await _enrich(db, r, current_user.id if current_user else None) for r in rows]
    return ListingListResponse(total=total, page=page, size=size, items=items)


@router.post("/models")
async def create_model(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new model listing (placeholder)."""
    raise HTTPException(401, "model creation requires provider role")


# ---------- GET /listings (search + sort) ----------------------------------

@router.get("/listings", response_model=ListingListResponse)
async def search_listings(
    q: Optional[str] = None,
    sort: Optional[str] = None,
    task: Optional[str] = None,
    framework: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListingListResponse:
    """Search listings with free-text `q`, sort by top_rated|newest."""
    query = select(ModelListing).where(ModelListing.visibility == "public")

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            ModelListing.name.ilike(term),
            ModelListing.description.ilike(term),
        ))
    if task:
        query = query.where(ModelListing.task == task)
    if framework:
        query = query.where(ModelListing.framework == framework)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    if sort == "newest":
        query = query.order_by(desc(ModelListing.created_at))
    elif sort == "top_rated":
        # Subquery: avg rating per listing
        avg_sub = (
            select(
                ModelListingReview.listing_id,
                func.avg(ModelListingReview.rating).label("avg_rating"),
                func.count(ModelListingReview.id).label("rev_count"),
            )
            .group_by(ModelListingReview.listing_id)
            .subquery()
        )
        query = query.outerjoin(avg_sub, avg_sub.c.listing_id == ModelListing.id)
        query = query.order_by(
            desc(avg_sub.c.rev_count),  # reviewed first
            desc(avg_sub.c.avg_rating),  # then by rating
            desc(ModelListing.created_at),
        )
    else:
        query = query.order_by(desc(ModelListing.created_at))

    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    rows = (await db.execute(query)).scalars().all()

    uid = current_user.id if current_user else None
    items = [await _enrich(db, r, uid) for r in rows]
    return ListingListResponse(total=total, page=page, size=size, items=items)


# ---------- GET /listings/{id} (detail) ------------------------------------

@router.get("/listings/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListingOut:
    listing = (
        await db.execute(select(ModelListing).where(ModelListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise HTTPException(404, "listing not found")
    uid = current_user.id if current_user else None
    return await _enrich(db, listing, uid)


# ---------- GET /listings/{id}/similar -------------------------------------

@router.get("/listings/{listing_id}/similar", response_model=List[ListingOut])
async def similar_listings(
    listing_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ListingOut]:
    seed = (
        await db.execute(select(ModelListing).where(ModelListing.id == listing_id))
    ).scalar_one_or_none()
    if seed is None:
        raise HTTPException(404, "listing not found")

    # Find candidates: same task, public visibility, exclude self
    q = (
        select(ModelListing)
        .where(
            ModelListing.visibility == "public",
            ModelListing.id != listing_id,
            ModelListing.task == seed.task,
        )
    )
    candidates = (await db.execute(q)).scalars().all()

    # Score by: same framework (+2), shared tags (+1 per tag)
    def _score(c: ModelListing) -> int:
        s = 0
        if c.framework == seed.framework:
            s += 2
        seed_tags = set(seed.tags or [])
        c_tags = set(c.tags or [])
        s += len(seed_tags & c_tags)
        return s

    candidates.sort(key=_score, reverse=True)
    top = candidates[:limit]
    uid = current_user.id if current_user else None
    return [await _enrich(db, c, uid) for c in top]


# ---------- GET /facets -----------------------------------------------------

@router.get("/facets", response_model=FacetsOut)
async def get_facets(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FacetsOut:
    q = select(ModelListing).where(ModelListing.visibility == "public")
    rows = (await db.execute(q)).scalars().all()

    tasks: dict[str, int] = {}
    frameworks: dict[str, int] = {}
    tags: dict[str, int] = {}
    for r in rows:
        tasks[r.task] = tasks.get(r.task, 0) + 1
        frameworks[r.framework] = frameworks.get(r.framework, 0) + 1
        for t in (r.tags or []):
            tags[t] = tags.get(t, 0) + 1

    return FacetsOut(tasks=tasks, frameworks=frameworks, tags=tags, total=len(rows))


# ---------- GET /favorites (my favorited listings) -------------------------

@router.get("/favorites", response_model=List[ListingOut])
async def list_my_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ListingOut]:
    """List listings favorited by the current user."""
    fav_listings = (
        await db.execute(
            select(ModelListing)
            .join(ModelFavorite, ModelFavorite.listing_id == ModelListing.id)
            .where(ModelFavorite.user_id == current_user.id)
            .order_by(desc(ModelListing.created_at))
        )
    ).scalars().all()
    return [await _enrich(db, r, current_user.id) for r in fav_listings]


# ---------- POST/DELETE /listings/{id}/favorite ----------------------------

@router.post("/listings/{listing_id}/favorite", response_model=FavoriteOut, status_code=201)
async def star_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteOut:
    listing = (
        await db.execute(select(ModelListing).where(ModelListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise HTTPException(404, "listing not found")

    # Idempotent: if already favorited, return existing
    existing = (
        await db.execute(
            select(ModelFavorite).where(
                ModelFavorite.listing_id == listing_id,
                ModelFavorite.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        fav = ModelFavorite(listing_id=listing_id, user_id=current_user.id)
        db.add(fav)
        await db.commit()
        await db.refresh(fav)
        return FavoriteOut(id=fav.id, favorited=True)
    return FavoriteOut(id=existing.id, favorited=True)


@router.delete("/listings/{listing_id}/favorite")
async def unstar_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(
            select(ModelFavorite).where(
                ModelFavorite.listing_id == listing_id,
                ModelFavorite.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"favorited": False}


# ---------- POST/GET/DELETE /listings/{id}/reviews -------------------------

@router.post("/listings/{listing_id}/reviews", response_model=ReviewOut, status_code=201)
async def create_review(
    listing_id: UUID,
    req: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewOut:
    listing = (
        await db.execute(select(ModelListing).where(ModelListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise HTTPException(404, "listing not found")

    # Upsert: one review per user per listing
    existing = (
        await db.execute(
            select(ModelListingReview).where(
                ModelListingReview.listing_id == listing_id,
                ModelListingReview.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.rating = req.rating
        existing.comment = req.comment
        await db.commit()
        await db.refresh(existing)
        return ReviewOut.model_validate(existing)

    review = ModelListingReview(
        listing_id=listing_id,
        user_id=current_user.id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return ReviewOut.model_validate(review)


@router.get("/listings/{listing_id}/reviews", response_model=List[ReviewOut])
async def list_reviews(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> List[ReviewOut]:
    rows = (
        await db.execute(
            select(ModelListingReview)
            .where(ModelListingReview.listing_id == listing_id)
            .order_by(desc(ModelListingReview.created_at))
        )
    ).scalars().all()
    return [ReviewOut.model_validate(r) for r in rows]


@router.get("/listings/{listing_id}/reviews/aggregate", response_model=ReviewAggregateOut)
async def review_aggregate(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReviewAggregateOut:
    rows = (
        await db.execute(
            select(ModelListingReview).where(ModelListingReview.listing_id == listing_id)
        )
    ).scalars().all()

    count = len(rows)
    avg = sum(r.rating for r in rows) / count if count else None
    hist = {str(i): 0 for i in range(1, 6)}
    for r in rows:
        hist[str(r.rating)] = hist.get(str(r.rating), 0) + 1

    return ReviewAggregateOut(
        review_count=count,
        average_rating=round(avg, 2) if avg else None,
        rating_histogram=hist,
    )


@router.delete("/listings/{listing_id}/reviews/mine")
async def delete_my_review(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(
            select(ModelListingReview).where(
                ModelListingReview.listing_id == listing_id,
                ModelListingReview.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"deleted": True}


# ---------- GET /deployments/{id}/usage-daily -------------------------------

@router.get("/deployments/{deployment_id}/usage-daily", response_model=DailyUsageOut)
async def deployment_usage_daily(
    deployment_id: UUID,
    since_days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyUsageOut:
    dep = (
        await db.execute(
            select(ModelDeployment).where(ModelDeployment.id == deployment_id)
        )
    ).scalar_one_or_none()
    if dep is None:
        raise HTTPException(404, "deployment not found")

    # Cross-org check: non-admin can only see own org
    if current_user.role != "admin" and dep.org_id != getattr(current_user, "org_id", None):
        raise HTTPException(403, "cannot view usage for other org")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days)

    events = (
        await db.execute(
            select(ModelUsageEvent).where(
                ModelUsageEvent.deployment_id == deployment_id,
                ModelUsageEvent.created_at >= cutoff,
            ).order_by(ModelUsageEvent.created_at)
        )
    ).scalars().all()

    # Group by day and backfill zero days
    daily_map: dict[str, dict] = {}
    for e in events:
        day_key = e.created_at.strftime("%Y-%m-%d") if e.created_at else "unknown"
        if day_key not in daily_map:
            daily_map[day_key] = {"ok": 0, "error": 0, "total": 0}
        outcome = e.outcome if e.outcome in ("ok", "error") else "ok"
        units = int(e.units or 1)
        daily_map[day_key][outcome] = daily_map[day_key].get(outcome, 0) + units
        daily_map[day_key]["total"] += units

    # Backfill all days in range
    points = []
    for i in range(since_days):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in daily_map:
            dm = daily_map[d]
            points.append({
                "date": d,
                "total_units": dm["total"],
                "by_outcome": {"ok": dm["ok"], "error": dm["error"]},
            })
        else:
            points.append({
                "date": d,
                "total_units": 0,
                "by_outcome": {"ok": 0, "error": 0},
            })

    # Sort by date ascending
    points.sort(key=lambda p: p["date"])

    return DailyUsageOut(
        quota_calls_per_day=dep.quota_calls_per_day,
        since_days=since_days,
        points=points,
    )
