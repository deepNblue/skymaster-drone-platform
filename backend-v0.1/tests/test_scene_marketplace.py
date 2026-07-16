"""v2.1 T2.0 · scene_marketplace pure-function tests.

Tests the slug helper and DB-level publish/browse/clone/review flows using
the SQLite fixture from conftest. We don't hit the HTTP layer here — that's
covered by later integration tests when auth wiring is in place.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import scene_marketplace as svc
from app.models.scene import Scene
from app.models.scene_marketplace import SceneListing, SCENE_LISTING_LICENSES


# ---------- slugify -------------------------------------------------------


def test_slugify_basic():
    assert svc.slugify("Chengdu East Rail 2026") == "chengdu-east-rail-2026"


def test_slugify_multiple_delimiters_collapse():
    assert svc.slugify("Hello - -- ___ World") == "hello-world"


def test_slugify_trims_leading_trailing_dashes():
    assert svc.slugify("  --hello--  ") == "hello"


def test_slugify_cjk_becomes_empty():
    # Non-ASCII entirely collapses; caller must supply explicit slug.
    assert svc.slugify("中华人民共和国") == ""


def test_slugify_truncates_to_80():
    long_title = "a" * 200
    assert len(svc.slugify(long_title)) == 80


def test_slugify_preserves_digits():
    assert svc.slugify("Site 42 · Version 3.1") == "site-42-version-3-1"


# ---------- DB tests using conftest.client (SQLite) ----------------------


@pytest_asyncio.fixture
async def session(client):  # noqa: ARG001  — reuse conftest.client for schema init
    """Yield an AsyncSession sharing the same in-memory SQLite as the app."""
    from app.db import engine
    Sess = async_sessionmaker(engine, expire_on_commit=False)
    async with Sess() as s:
        yield s


async def _make_scene(session: AsyncSession, org_id: UUID, status: str = "ready") -> Scene:
    scene = Scene(
        id=uuid4(),
        org_id=org_id,
        name=f"Scene {uuid4().hex[:6]}",
        description="unit test scene",
        status=status,
        owner_user_id=None,
        n_gaussians=1_000_000,
    )
    session.add(scene)
    await session.commit()
    await session.refresh(scene)
    return scene


@pytest.mark.asyncio
async def test_publish_scene_happy_path(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=scene.id,
        org_id=org,
        publisher_user_id=None,
        title="My Marketplace Scene",
        description="Test",
        tags=["urban", "drone"],
        license="CC-BY-NC",
    ))
    await session.commit()
    assert listing.slug == "my-marketplace-scene"
    assert listing.n_gaussians == 1_000_000
    assert listing.status == "active"


@pytest.mark.asyncio
async def test_publish_rejects_draft_scene(session):
    org = uuid4()
    scene = await _make_scene(session, org, status="draft")
    with pytest.raises(svc.SceneNotPublishable):
        await svc.publish_scene(session, svc.PublishParams(
            scene_id=scene.id, org_id=org,
            publisher_user_id=None, title="x",
        ))


@pytest.mark.asyncio
async def test_publish_rejects_wrong_org(session):
    real_org = uuid4()
    other_org = uuid4()
    scene = await _make_scene(session, real_org)
    with pytest.raises(svc.SceneNotPublishable):
        await svc.publish_scene(session, svc.PublishParams(
            scene_id=scene.id, org_id=other_org,
            publisher_user_id=None, title="x",
        ))


@pytest.mark.asyncio
async def test_publish_rejects_unknown_license(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    with pytest.raises(svc.InvalidLicense):
        await svc.publish_scene(session, svc.PublishParams(
            scene_id=scene.id, org_id=org,
            publisher_user_id=None, title="x",
            license="MIT-NC-BOGUS",
        ))


@pytest.mark.asyncio
async def test_publish_slug_conflict(session):
    org = uuid4()
    s1 = await _make_scene(session, org)
    s2 = await _make_scene(session, org)
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s1.id, org_id=org, publisher_user_id=None,
        title="Unique Title Alpha",
    ))
    await session.commit()
    with pytest.raises(svc.SlugConflict):
        await svc.publish_scene(session, svc.PublishParams(
            scene_id=s2.id, org_id=org, publisher_user_id=None,
            title="Unique Title Alpha",  # same title → same slug
        ))


@pytest.mark.asyncio
async def test_publish_auto_slug_for_cjk_title(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=scene.id, org_id=org, publisher_user_id=None,
        title="西南交大老校区",  # pure CJK → slugify empty → fallback
    ))
    await session.commit()
    assert listing.slug.startswith("scene-")
    assert len(listing.slug) >= 10


@pytest.mark.asyncio
async def test_browse_filters_by_visibility(session):
    org_a = uuid4()
    org_b = uuid4()

    s_pub = await _make_scene(session, org_a)
    s_org = await _make_scene(session, org_a)
    s_unl = await _make_scene(session, org_a)

    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s_pub.id, org_id=org_a, publisher_user_id=None,
        title="Public Alpha", visibility="public",
    ))
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s_org.id, org_id=org_a, publisher_user_id=None,
        title="Org Only Beta", visibility="org_only",
    ))
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s_unl.id, org_id=org_a, publisher_user_id=None,
        title="Unlisted Gamma", visibility="unlisted",
    ))
    await session.commit()

    # Viewer in org_b sees only public
    rows, total = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org_b,
    ))
    titles = {r.title for r in rows}
    assert "Public Alpha" in titles
    assert "Org Only Beta" not in titles

    # Viewer in org_a sees public + org_only
    rows, total = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org_a,
    ))
    titles = {r.title for r in rows}
    assert "Public Alpha" in titles
    assert "Org Only Beta" in titles


@pytest.mark.asyncio
async def test_browse_filter_by_min_gaussians(session):
    org = uuid4()
    # Create with distinct n_gaussians values via direct insert to avoid
    # SQLite onupdate issue.
    small = Scene(
        id=uuid4(), org_id=org, name="small",
        status="ready", n_gaussians=100_000,
    )
    big = Scene(
        id=uuid4(), org_id=org, name="big",
        status="ready", n_gaussians=5_000_000,
    )
    session.add(small)
    session.add(big)
    await session.commit()

    await svc.publish_scene(session, svc.PublishParams(
        scene_id=small.id, org_id=org, publisher_user_id=None, title="small-listing",
    ))
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=big.id, org_id=org, publisher_user_id=None, title="big-listing",
    ))
    await session.commit()

    rows, _ = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org, min_gaussians=1_000_000,
    ))
    titles = {r.title for r in rows}
    assert titles == {"big-listing"}


@pytest.mark.asyncio
async def test_clone_creates_new_scene_and_records(session):
    seller_org = uuid4()
    buyer_org = uuid4()
    buyer_user = uuid4()
    src_scene = await _make_scene(session, seller_org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=src_scene.id, org_id=seller_org,
        publisher_user_id=None, title="Clone Me",
    ))
    await session.commit()

    new_scene, clone_rec = await svc.clone_listing(
        session, listing.id, buyer_user, buyer_org,
    )
    await session.commit()
    assert new_scene.org_id == buyer_org
    assert new_scene.status == "archived"
    assert new_scene.name.startswith("[clone]")
    assert clone_rec.listing_id == listing.id
    assert clone_rec.cloned_by_org_id == buyer_org

    # clone_count incremented
    fresh = (await session.execute(
        select(SceneListing).where(SceneListing.id == listing.id)
    )).scalar_one()
    assert fresh.clone_count == 1


@pytest.mark.asyncio
async def test_clone_rejects_org_only_listing_across_orgs(session):
    seller_org = uuid4()
    buyer_org = uuid4()
    buyer_user = uuid4()
    src_scene = await _make_scene(session, seller_org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=src_scene.id, org_id=seller_org, publisher_user_id=None,
        title="Internal Only", visibility="org_only",
    ))
    await session.commit()
    with pytest.raises(svc.ListingNotVisible):
        await svc.clone_listing(session, listing.id, buyer_user, buyer_org)


@pytest.mark.asyncio
async def test_review_upsert_and_summary(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=scene.id, org_id=org, publisher_user_id=None, title="Rated Scene",
    ))
    await session.commit()

    user_a = uuid4()
    user_b = uuid4()
    await svc.upsert_review(session, listing.id, user_a, 5, "great")
    await svc.upsert_review(session, listing.id, user_b, 3, None)
    await session.commit()

    # Same user re-reviews → updates in place, not duplicated
    await svc.upsert_review(session, listing.id, user_a, 4, "adjusted")
    await session.commit()

    summary = await svc.listing_rating_summary(session, listing.id)
    assert summary["count"] == 2
    assert summary["average"] == 3.5


@pytest.mark.asyncio
async def test_review_out_of_range_rejected(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=scene.id, org_id=org, publisher_user_id=None, title="R",
    ))
    await session.commit()
    with pytest.raises(svc.MarketplaceError):
        await svc.upsert_review(session, listing.id, uuid4(), 0, None)
    with pytest.raises(svc.MarketplaceError):
        await svc.upsert_review(session, listing.id, uuid4(), 6, None)


@pytest.mark.asyncio
async def test_browse_pagination_bounds(session):
    with pytest.raises(svc.MarketplaceError):
        await svc.browse_listings(session, svc.BrowseFilter(limit=0))
    with pytest.raises(svc.MarketplaceError):
        await svc.browse_listings(session, svc.BrowseFilter(limit=101))
    with pytest.raises(svc.MarketplaceError):
        await svc.browse_listings(session, svc.BrowseFilter(offset=-1))


# ============================================================================
# T2.1 · Discovery + moderation tests
# ============================================================================


@pytest.mark.asyncio
async def test_publish_rejects_unknown_category(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    with pytest.raises(svc.MarketplaceError):
        await svc.publish_scene(session, svc.PublishParams(
            scene_id=scene.id, org_id=org, publisher_user_id=None,
            title="cat test", category="bogus-cat",
        ))


@pytest.mark.asyncio
async def test_category_filter_and_counts(session):
    org = uuid4()
    s1 = await _make_scene(session, org)
    s2 = await _make_scene(session, org)
    s3 = await _make_scene(session, org)

    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s1.id, org_id=org, publisher_user_id=None,
        title="Chengdu Old Town", category="tourism",
    ))
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s2.id, org_id=org, publisher_user_id=None,
        title="Chengdu East Rail Site", category="engineering",
    ))
    await svc.publish_scene(session, svc.PublishParams(
        scene_id=s3.id, org_id=org, publisher_user_id=None,
        title="Uncategorized Scene",  # no category → None
    ))
    await session.commit()

    counts = await svc.category_counts(session, viewer_org_id=org)
    m = {c["category"]: c["count"] for c in counts}
    assert m["tourism"] == 1
    assert m["engineering"] == 1
    # Category "other" bucket should include the uncategorized listing
    # via SQL grouping on NULL → we map it to "other" in the helper.
    assert m["other"] >= 1

    # Category filter on browse
    rows, _ = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org, category="tourism",
    ))
    assert {r.title for r in rows} == {"Chengdu Old Town"}


@pytest.mark.asyncio
async def test_toggle_featured_and_featured_sort(session):
    org = uuid4()
    scenes = [await _make_scene(session, org) for _ in range(3)]
    listings = []
    for i, sc in enumerate(scenes):
        listings.append(await svc.publish_scene(session, svc.PublishParams(
            scene_id=sc.id, org_id=org, publisher_user_id=None,
            title=f"Listing {i}",
        )))
    await session.commit()

    # Feature the middle listing
    featured = await svc.toggle_featured(
        session, listings[1].id, True, note="Editor's pick this week",
    )
    await session.commit()
    assert featured.is_featured is True
    assert featured.featured_note == "Editor's pick this week"
    assert featured.featured_at is not None

    # Featured-only filter returns only that one
    rows, total = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org, featured_only=True,
    ))
    assert total == 1
    assert rows[0].id == listings[1].id

    # Sort by "featured" puts featured first regardless of created_at
    rows, _ = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org, sort="featured",
    ))
    assert rows[0].id == listings[1].id

    # Un-feature clears flags
    unfeatured = await svc.toggle_featured(session, listings[1].id, False)
    await session.commit()
    assert unfeatured.is_featured is False
    assert unfeatured.featured_at is None


@pytest.mark.asyncio
async def test_moderate_listing_transitions(session):
    org = uuid4()
    scene = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=scene.id, org_id=org, publisher_user_id=None,
        title="Naughty Listing",
    ))
    await session.commit()

    # active → archived
    await svc.moderate_listing(session, listing.id, "archived")
    await session.commit()
    assert listing.status == "archived"

    # archived → removed requires reason
    with pytest.raises(svc.MarketplaceError):
        await svc.moderate_listing(session, listing.id, "removed")

    await svc.moderate_listing(session, listing.id, "removed", reason="policy violation")
    await session.commit()
    assert listing.status == "removed"
    assert listing.is_featured is False  # removed listings auto-drop featured

    # Removed listings should NOT appear in browse
    rows, total = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org,
    ))
    assert not any(r.id == listing.id for r in rows)

    # Invalid status rejected
    with pytest.raises(svc.MarketplaceError):
        await svc.moderate_listing(session, listing.id, "bogus")


@pytest.mark.asyncio
async def test_sort_by_popular(session):
    """Popular sort orders by clone_count desc."""
    org = uuid4()
    buyer_org = uuid4()
    buyer_user = uuid4()

    listings = []
    for i in range(3):
        sc = await _make_scene(session, org)
        l = await svc.publish_scene(session, svc.PublishParams(
            scene_id=sc.id, org_id=org, publisher_user_id=None,
            title=f"L{i}",
        ))
        listings.append(l)
    await session.commit()

    # Clone L1 three times, L2 once, L0 zero
    for _ in range(3):
        await svc.clone_listing(session, listings[1].id, buyer_user, buyer_org)
    await svc.clone_listing(session, listings[2].id, buyer_user, buyer_org)
    await session.commit()

    rows, _ = await svc.browse_listings(session, svc.BrowseFilter(
        viewer_org_id=org, sort="popular",
    ))
    # L1 (3 clones) > L2 (1 clone) > L0 (0 clones)
    ids = [r.id for r in rows]
    assert ids.index(listings[1].id) < ids.index(listings[2].id)
    assert ids.index(listings[2].id) < ids.index(listings[0].id)


@pytest.mark.asyncio
async def test_trending_falls_back_to_overall_when_no_recent_clones(session):
    org = uuid4()
    buyer_org = uuid4()
    buyer_user = uuid4()

    sc = await _make_scene(session, org)
    listing = await svc.publish_scene(session, svc.PublishParams(
        scene_id=sc.id, org_id=org, publisher_user_id=None,
        title="Old Popular",
    ))
    await session.commit()

    await svc.clone_listing(session, listing.id, buyer_user, buyer_org)
    await session.commit()

    # Backdate the clone to 30 days ago so it's outside the 7-day trending window
    from app.models.scene_marketplace import SceneListingClone
    from sqlalchemy import update
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await session.execute(
        update(SceneListingClone).values(created_at=old)
    )
    await session.commit()

    # No recent clones → trending should fall back to overall clone_count
    rows = await svc.trending_listings(session, viewer_org_id=org, days=7)
    assert any(r.id == listing.id for r in rows)
