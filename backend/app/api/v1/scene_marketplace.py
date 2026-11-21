"""Scene marketplace REST API — v2.1 T2.0."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.scene_marketplace import (
    SCENE_LISTING_LICENSES, SCENE_LISTING_VISIBILITIES, SceneListing,
)
from app.models.user import User
from app.services import scene_marketplace as svc

router = APIRouter(prefix="/marketplace/scenes", tags=["scene-marketplace"])


# ---------- schemas --------------------------------------------------------


class PublishBody(BaseModel):
    scene_id: UUID
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=4000)
    tags: Optional[list[str]] = None
    license: str = Field("CC-BY-NC")
    price_cents: int = Field(0, ge=0)
    visibility: str = Field("public")
    slug: Optional[str] = Field(None, min_length=1, max_length=96)
    cover_asset_id: Optional[UUID] = None
    category: Optional[str] = None


class ListingOut(BaseModel):
    id: UUID
    scene_id: UUID
    org_id: UUID
    slug: str
    title: str
    description: Optional[str]
    tags: Optional[list]
    visibility: str
    status: str
    license: str
    price_cents: int
    category: Optional[str] = None
    is_featured: bool = False
    featured_note: Optional[str] = None
    n_gaussians: Optional[int]
    n_points: Optional[int]
    clone_count: int
    view_count: int

    class Config:
        from_attributes = True


class ListingPage(BaseModel):
    total: int
    items: list[ListingOut]
    limit: int
    offset: int


class ReviewBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=2000)


class ReviewOut(BaseModel):
    id: UUID
    listing_id: UUID
    user_id: UUID
    rating: int
    comment: Optional[str]

    class Config:
        from_attributes = True


class RatingSummary(BaseModel):
    count: int
    average: Optional[float]


class CloneOut(BaseModel):
    scene_id: UUID
    listing_id: UUID
    cloned_by_org_id: UUID


# ---------- helpers --------------------------------------------------------


def _map_svc_error(e: svc.MarketplaceError) -> HTTPException:
    status = 400
    if isinstance(e, svc.ListingNotVisible):
        status = 403
    if "not found" in str(e):
        status = 404
    if isinstance(e, svc.SlugConflict):
        status = 409
    return HTTPException(status, str(e))


# ---------- endpoints ------------------------------------------------------


@router.post("", response_model=ListingOut, status_code=201)
async def publish(
    body: PublishBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingOut:
    try:
        listing = await svc.publish_scene(db, svc.PublishParams(
            scene_id=body.scene_id,
            org_id=user.org_id,
            publisher_user_id=user.id,
            title=body.title,
            description=body.description,
            tags=body.tags,
            license=body.license,
            price_cents=body.price_cents,
            visibility=body.visibility,
            slug=body.slug,
            cover_asset_id=body.cover_asset_id,
            category=body.category,
        ))
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    await db.commit()
    return listing


@router.get("/facets")
async def get_scene_facets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """T7.11 — facet counts for the scene marketplace filter sidebar.

    Same shape as T5.13 (model marketplace facets):
      * categories: {category → count}
      * licenses: {license → count}
      * tags: top-30 tag counts (JSONB[] fold in Python)
      * total: total public scene count

    Public-only scope — private scenes never leak into counts.
    """
    from app.models.scene_marketplace import SceneListing

    cat_rows = (await db.execute(
        select(SceneListing.category, func.count(SceneListing.id))
        .where(SceneListing.visibility == "public")
        .group_by(SceneListing.category)
    )).all()
    categories = {c: int(n) for c, n in cat_rows if c}

    lic_rows = (await db.execute(
        select(SceneListing.license, func.count(SceneListing.id))
        .where(SceneListing.visibility == "public")
        .group_by(SceneListing.license)
    )).all()
    licenses = {l: int(n) for l, n in lic_rows if l}

    tag_rows = (await db.execute(
        select(SceneListing.tags)
        .where(SceneListing.visibility == "public")
    )).all()
    tag_counts: dict[str, int] = {}
    for (tags,) in tag_rows:
        for t in (tags or []):
            if not isinstance(t, str):
                continue
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = dict(
        sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:30]
    )

    total = (await db.execute(
        select(func.count(SceneListing.id))
        .where(SceneListing.visibility == "public")
    )).scalar_one()

    return {
        "categories": categories,
        "licenses": licenses,
        "tags": top_tags,
        "total": int(total),
    }


@router.get("", response_model=ListingPage)
async def browse(
    q: Optional[str] = None,
    tags: Optional[str] = Query(None, description="comma-separated"),
    min_gaussians: Optional[int] = None,
    license: Optional[str] = None,
    category: Optional[str] = None,
    featured_only: bool = False,
    sort: str = "recent",
    org_id: Optional[UUID] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingPage:
    try:
        flt = svc.BrowseFilter(
            q=q,
            tags=[t.strip() for t in tags.split(",")] if tags else None,
            min_gaussians=min_gaussians,
            license=license,
            category=category,
            featured_only=featured_only,
            sort=sort,
            org_id=org_id,
            viewer_org_id=user.org_id,
            limit=limit,
            offset=offset,
        )
        rows, total = await svc.browse_listings(db, flt)
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    return ListingPage(
        total=total, items=list(rows),
        limit=limit, offset=offset,
    )


@router.post("/{listing_id}/clone", response_model=CloneOut, status_code=201)
async def clone(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CloneOut:
    try:
        new_scene, clone_rec = await svc.clone_listing(
            db, listing_id, user.id, user.org_id,
        )
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    await db.commit()
    return CloneOut(
        scene_id=new_scene.id,
        listing_id=clone_rec.listing_id,
        cloned_by_org_id=clone_rec.cloned_by_org_id,
    )


@router.post("/{listing_id}/reviews", response_model=ReviewOut, status_code=201)
async def review(
    listing_id: UUID,
    body: ReviewBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewOut:
    try:
        r = await svc.upsert_review(
            db, listing_id, user.id, body.rating, body.comment,
        )
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    await db.commit()
    return r


@router.get("/{listing_id}/rating", response_model=RatingSummary)
async def rating(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RatingSummary:
    summary = await svc.listing_rating_summary(db, listing_id)
    return RatingSummary(**summary)


# ============================================================================
# T2.1 · Discovery + moderation endpoints
# ============================================================================


class CategoryCount(BaseModel):
    category: str
    count: int


class ModerateBody(BaseModel):
    new_status: str = Field(..., description="active|archived|removed")
    reason: Optional[str] = Field(None, max_length=500)


class FeatureBody(BaseModel):
    featured: bool
    note: Optional[str] = Field(None, max_length=200)


def _require_admin(user: User) -> None:
    role = getattr(user, "role", None)
    if role not in ("admin", "superadmin"):
        raise HTTPException(403, "admin-only endpoint")


@router.get("/discovery/categories", response_model=list[CategoryCount])
async def discover_categories(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CategoryCount]:
    rows = await svc.category_counts(db, viewer_org_id=user.org_id)
    return [CategoryCount(**r) for r in rows]


@router.get("/discovery/trending", response_model=list[ListingOut])
async def discover_trending(
    limit: int = 10,
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ListingOut]:
    try:
        rows = await svc.trending_listings(
            db, viewer_org_id=user.org_id, limit=limit, days=days,
        )
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    return list(rows)


@router.post("/{listing_id}/feature", response_model=ListingOut)
async def feature(
    listing_id: UUID,
    body: FeatureBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingOut:
    _require_admin(user)
    try:
        listing = await svc.toggle_featured(
            db, listing_id, body.featured, body.note,
        )
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    await db.commit()
    return listing


@router.post("/{listing_id}/moderate", response_model=ListingOut)
async def moderate(
    listing_id: UUID,
    body: ModerateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListingOut:
    _require_admin(user)
    try:
        listing = await svc.moderate_listing(
            db, listing_id, body.new_status, body.reason,
        )
    except svc.MarketplaceError as e:
        raise _map_svc_error(e)
    await db.commit()
    return listing
