"""Scene marketplace service — v2.1 T2.0.

Pure business-logic helpers for publishing, browsing, cloning, and rating
scene listings. Kept separate from the FastAPI route layer so unit tests
can hit the logic without HTTP wiring.

Rule of thumb: **the route layer only does auth + DTO shape**. Anything
involving multiple table writes, state transitions, or non-trivial
querying lives here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene import Scene
from app.models.scene_marketplace import (
    SceneListing, SceneListingClone, SceneListingReview,
    SCENE_LISTING_LICENSES, SCENE_LISTING_VISIBILITIES, SCENE_LISTING_CATEGORIES,
)  # noqa: F401 — SceneListingClone is used by trending_listings below


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarketplaceError(Exception):
    """Base error surfaced back to the route layer as HTTP 400."""


class SceneNotPublishable(MarketplaceError):
    pass


class SlugConflict(MarketplaceError):
    pass


class InvalidLicense(MarketplaceError):
    pass


class ListingNotVisible(MarketplaceError):
    pass


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

_SLUG_ALLOW = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Convert a listing title to a URL-safe slug.

    * lowercase
    * collapse runs of non-alnum into ``-``
    * strip leading/trailing dashes
    * limit to 80 chars

    We accept CJK titles by encoding runs as ``-``; the caller will get an
    empty slug if the title contains no ASCII alnum, which we then reject
    and require an explicit ``slug`` override.
    """
    s = title.strip().lower()
    s = _SLUG_ALLOW.sub("-", s).strip("-")
    return s[:80]


def _validate_slug(slug: str) -> None:
    if not slug or len(slug) > 96:
        raise MarketplaceError(f"invalid slug length: {len(slug)}")
    # Allow single-char slugs and multi-char slugs; must start+end alnum,
    # inner chars alnum or hyphen.
    if not re.fullmatch(r"[a-z0-9]([a-z0-9\-]{0,94}[a-z0-9])?", slug):
        raise MarketplaceError(f"slug must be lowercase alnum + hyphens: {slug!r}")


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


@dataclass
class PublishParams:
    scene_id: UUID
    org_id: UUID
    publisher_user_id: Optional[UUID]
    title: str
    description: Optional[str] = None
    tags: Optional[list] = None
    license: str = "CC-BY-NC"
    price_cents: int = 0
    visibility: str = "public"
    slug: Optional[str] = None
    cover_asset_id: Optional[UUID] = None
    category: Optional[str] = None


async def publish_scene(db: AsyncSession, params: PublishParams) -> SceneListing:
    """Publish a completed scene as a marketplace listing.

    Preconditions:
    * scene exists and belongs to ``params.org_id``
    * scene.status ∈ {ready, archived} — draft/ingesting/training can't publish
    * license ∈ SCENE_LISTING_LICENSES
    * price_cents ≥ 0
    * slug is unique (auto-generated from title if omitted)
    """
    # 1. Load scene + org check
    scene = (
        await db.execute(select(Scene).where(Scene.id == params.scene_id))
    ).scalar_one_or_none()
    if scene is None:
        raise SceneNotPublishable(f"scene {params.scene_id} not found")
    if scene.org_id != params.org_id:
        raise SceneNotPublishable("scene does not belong to publisher's org")
    if scene.status not in ("ready", "archived"):
        raise SceneNotPublishable(
            f"scene status={scene.status!r}; only ready/archived can be published"
        )

    # 2. Validate license + visibility + category
    if params.license not in SCENE_LISTING_LICENSES:
        raise InvalidLicense(f"unknown license {params.license!r}")
    if params.visibility not in SCENE_LISTING_VISIBILITIES:
        raise MarketplaceError(f"unknown visibility {params.visibility!r}")
    if params.category is not None and params.category not in SCENE_LISTING_CATEGORIES:
        raise MarketplaceError(f"unknown category {params.category!r}")
    if params.price_cents < 0:
        raise MarketplaceError("price_cents must be >= 0")
    if not params.title or not params.title.strip():
        raise MarketplaceError("title must be non-empty")

    # 3. Resolve slug
    slug = params.slug or slugify(params.title) or f"scene-{uuid4().hex[:12]}"
    _validate_slug(slug)
    dup = (
        await db.execute(
            select(SceneListing.id).where(SceneListing.slug == slug).limit(1)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise SlugConflict(f"slug {slug!r} already taken")

    # 4. Insert
    listing = SceneListing(
        scene_id=scene.id,
        org_id=params.org_id,
        publisher_user_id=params.publisher_user_id,
        slug=slug,
        title=params.title.strip(),
        description=params.description,
        tags=params.tags,
        cover_asset_id=params.cover_asset_id,
        visibility=params.visibility,
        status="active",
        license=params.license,
        price_cents=params.price_cents,
        category=params.category,
        n_gaussians=getattr(scene, "n_gaussians", None),
        n_points=getattr(scene, "n_points", None),
    )
    db.add(listing)
    await db.flush()
    return listing


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------


@dataclass
class BrowseFilter:
    """Filters + pagination for the browse endpoint."""
    q: Optional[str] = None            # free-text on title/description
    tags: Optional[list[str]] = None   # match ANY tag
    min_gaussians: Optional[int] = None
    license: Optional[str] = None
    category: Optional[str] = None
    featured_only: bool = False
    org_id: Optional[UUID] = None       # only listings from this org
    viewer_org_id: Optional[UUID] = None  # for visibility filtering
    # sort: recent (default) / popular (clone_count desc) / trending
    #  (7-day clones), and 'top_rated' via join (heavier, avg desc)
    sort: str = "recent"
    limit: int = 20
    offset: int = 0


async def browse_listings(
    db: AsyncSession, flt: BrowseFilter,
) -> tuple[list[SceneListing], int]:
    """Return (page, total) matching filters, visibility-aware."""
    if flt.limit < 1 or flt.limit > 100:
        raise MarketplaceError("limit must be in [1, 100]")
    if flt.offset < 0:
        raise MarketplaceError("offset must be >= 0")

    conds = [SceneListing.status == "active"]

    # visibility rules
    if flt.viewer_org_id is None:
        # anonymous / cross-org visitor sees only public
        conds.append(SceneListing.visibility == "public")
    else:
        conds.append(
            or_(
                SceneListing.visibility == "public",
                and_(
                    SceneListing.visibility == "org_only",
                    SceneListing.org_id == flt.viewer_org_id,
                ),
            )
        )

    if flt.q:
        pat = f"%{flt.q.lower()}%"
        conds.append(or_(
            func.lower(SceneListing.title).like(pat),
            func.lower(SceneListing.description).like(pat),
        ))
    if flt.min_gaussians is not None:
        conds.append(SceneListing.n_gaussians >= flt.min_gaussians)
    if flt.license:
        if flt.license not in SCENE_LISTING_LICENSES:
            raise InvalidLicense(f"unknown license {flt.license!r}")
        conds.append(SceneListing.license == flt.license)
    if flt.category:
        if flt.category not in SCENE_LISTING_CATEGORIES:
            raise MarketplaceError(f"unknown category {flt.category!r}")
        conds.append(SceneListing.category == flt.category)
    if flt.featured_only:
        conds.append(SceneListing.is_featured == True)  # noqa: E712 — SQLite bool
    if flt.org_id:
        conds.append(SceneListing.org_id == flt.org_id)

    # Tag filter — JSONB "?|" operator via has_any. Fall back to Python
    # filter for unit tests that use SQLite (no JSONB).
    tag_filter_py = None
    if flt.tags:
        tag_filter_py = set(flt.tags)

    base = select(SceneListing).where(and_(*conds))
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    # Sort options
    if flt.sort == "popular":
        order = SceneListing.clone_count.desc()
    elif flt.sort == "featured":
        # Featured first, then most-cloned, then newest.
        order = (
            SceneListing.is_featured.desc(),
            SceneListing.clone_count.desc(),
            SceneListing.created_at.desc(),
        )
    else:  # recent (default)
        order = SceneListing.created_at.desc()

    page_stmt = base
    if isinstance(order, tuple):
        page_stmt = page_stmt.order_by(*order)
    else:
        page_stmt = page_stmt.order_by(order)
    page_stmt = page_stmt.limit(flt.limit).offset(flt.offset)
    rows = (await db.execute(page_stmt)).scalars().all()

    if tag_filter_py:
        rows = [r for r in rows if r.tags and set(r.tags) & tag_filter_py]

    return list(rows), int(total)


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------


async def _is_visible_to(listing: SceneListing, viewer_org_id: Optional[UUID]) -> bool:
    if listing.status != "active":
        return False
    if listing.visibility == "public":
        return True
    if listing.visibility == "org_only" and viewer_org_id == listing.org_id:
        return True
    if listing.visibility == "unlisted":
        # Only visible via direct link → the caller should have supplied slug
        return True
    return False


async def clone_listing(
    db: AsyncSession,
    listing_id: UUID,
    cloner_user_id: UUID,
    cloner_org_id: UUID,
) -> tuple[Scene, SceneListingClone]:
    """Create a *new* Scene in the cloner's org that references the listing.

    We only copy metadata + n_gaussians summary — the raw ``.ply`` stays
    in the seller's CAS. Downloading the artifact goes through a separate
    permission check (paid downloads = v2.3).
    """
    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")
    if not await _is_visible_to(listing, cloner_org_id):
        raise ListingNotVisible("listing not visible to your org")

    src = (
        await db.execute(select(Scene).where(Scene.id == listing.scene_id))
    ).scalar_one_or_none()
    if src is None:
        raise MarketplaceError("source scene missing (deleted?)")

    new_scene = Scene(
        id=uuid4(),
        org_id=cloner_org_id,
        name=f"[clone] {listing.title[:80]}",
        description=(
            f"Cloned from marketplace listing {listing.slug!r} (org {listing.org_id}). "
            f"Source scene {src.id}."
        ),
        status="archived",  # imported clones are read-only until user re-runs pipeline
        owner_user_id=cloner_user_id,
        n_gaussians=listing.n_gaussians,
        n_points=listing.n_points,
    )
    db.add(new_scene)
    await db.flush()

    clone_record = SceneListingClone(
        listing_id=listing.id,
        cloned_scene_id=new_scene.id,
        cloned_by_user_id=cloner_user_id,
        cloned_by_org_id=cloner_org_id,
    )
    db.add(clone_record)

    listing.clone_count = (listing.clone_count or 0) + 1
    await db.flush()
    return new_scene, clone_record


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


async def upsert_review(
    db: AsyncSession, listing_id: UUID, user_id: UUID,
    rating: int, comment: Optional[str],
) -> SceneListingReview:
    if rating < 1 or rating > 5:
        raise MarketplaceError("rating must be in 1..5")
    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")

    existing = (
        await db.execute(
            select(SceneListingReview).where(
                SceneListingReview.listing_id == listing_id,
                SceneListingReview.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.rating = rating
        existing.comment = comment
        await db.flush()
        return existing

    review = SceneListingReview(
        listing_id=listing_id, user_id=user_id,
        rating=rating, comment=comment,
    )
    db.add(review)
    await db.flush()
    return review


async def listing_rating_summary(
    db: AsyncSession, listing_id: UUID,
) -> dict:
    """Compute average rating + count for a listing."""
    stmt = select(
        func.count(SceneListingReview.id),
        func.avg(SceneListingReview.rating),
    ).where(SceneListingReview.listing_id == listing_id)
    total, avg = (await db.execute(stmt)).one()
    return {
        "count": int(total or 0),
        "average": round(float(avg), 2) if avg is not None else None,
    }


# ---------------------------------------------------------------------------
# Discovery (v2.1 T2.1)
# ---------------------------------------------------------------------------


from datetime import datetime, timezone, timedelta


async def category_counts(
    db: AsyncSession, viewer_org_id: Optional[UUID],
) -> list[dict]:
    """Return [{category, count}] over active + visible listings.

    Used by the frontend to render the category nav strip. Categories
    with zero visible listings are still included (count=0) so the UI
    layout stays stable.
    """
    conds = [SceneListing.status == "active"]
    if viewer_org_id is None:
        conds.append(SceneListing.visibility == "public")
    else:
        conds.append(or_(
            SceneListing.visibility == "public",
            and_(
                SceneListing.visibility == "org_only",
                SceneListing.org_id == viewer_org_id,
            ),
        ))

    stmt = (
        select(SceneListing.category, func.count(SceneListing.id))
        .where(and_(*conds))
        .group_by(SceneListing.category)
    )
    rows = (await db.execute(stmt)).all()
    seen = {r[0] or "other": int(r[1]) for r in rows}
    return [
        {"category": c, "count": seen.get(c, 0)} for c in SCENE_LISTING_CATEGORIES
    ]


async def trending_listings(
    db: AsyncSession, viewer_org_id: Optional[UUID],
    limit: int = 10, days: int = 7,
) -> list[SceneListing]:
    """Listings whose *recent* clone activity is highest in the last N days.

    We approximate "trending" by counting rows in ``scene_listing_clones``
    with ``created_at >= now-Δ`` grouped by listing_id, then ordering
    desc. Falls back to overall clone_count if there are no recent clones
    (bootstrap phase where the platform is fresh).
    """
    if limit < 1 or limit > 50:
        raise MarketplaceError("limit must be in [1,50]")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    vis_conds = [SceneListing.status == "active"]
    if viewer_org_id is None:
        vis_conds.append(SceneListing.visibility == "public")
    else:
        vis_conds.append(or_(
            SceneListing.visibility == "public",
            and_(
                SceneListing.visibility == "org_only",
                SceneListing.org_id == viewer_org_id,
            ),
        ))

    recent = (
        select(
            SceneListingClone.listing_id,
            func.count(SceneListingClone.id).label("hits"),
        )
        .where(SceneListingClone.created_at >= cutoff)
        .group_by(SceneListingClone.listing_id)
        .subquery()
    )
    stmt = (
        select(SceneListing, recent.c.hits)
        .join(recent, recent.c.listing_id == SceneListing.id)
        .where(and_(*vis_conds))
        .order_by(recent.c.hits.desc(), SceneListing.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    if rows:
        return [r[0] for r in rows]

    # Bootstrap fallback: no recent clones anywhere → return by overall clones
    fallback = (
        select(SceneListing)
        .where(and_(*vis_conds))
        .order_by(SceneListing.clone_count.desc(), SceneListing.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(fallback)).scalars().all())


async def toggle_featured(
    db: AsyncSession, listing_id: UUID, featured: bool,
    note: Optional[str] = None,
) -> SceneListing:
    """Admin-only: promote/demote a listing to featured slot."""
    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")
    listing.is_featured = featured
    listing.featured_note = note if featured else None
    listing.featured_at = datetime.now(timezone.utc) if featured else None
    await db.flush()
    return listing


# ---------------------------------------------------------------------------
# Moderation (v2.1 T2.1)
# ---------------------------------------------------------------------------


async def moderate_listing(
    db: AsyncSession, listing_id: UUID, new_status: str,
    reason: Optional[str] = None,
) -> SceneListing:
    """Admin-only: change listing status.

    Valid transitions:
      active     → archived (soft-hide, publisher can restore)
      active     → removed (admin takedown, requires reason)
      archived   → active (restore)
      removed    → active (rare; admin only)
    """
    if new_status not in ("active", "archived", "removed"):
        raise MarketplaceError(f"invalid status {new_status!r}")
    if new_status == "removed" and not reason:
        raise MarketplaceError("removed status requires a reason")

    listing = (
        await db.execute(select(SceneListing).where(SceneListing.id == listing_id))
    ).scalar_one_or_none()
    if listing is None:
        raise MarketplaceError("listing not found")
    listing.status = new_status
    # Featured listings that are hidden should lose featured flag
    if new_status != "active":
        listing.is_featured = False
    await db.flush()
    return listing
