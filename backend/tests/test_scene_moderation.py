"""v2.1 T2.2 · Scene moderation report + appeal tests."""
from __future__ import annotations

from uuid import uuid4, UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import scene_marketplace as market_svc
from app.services import scene_moderation as mod_svc
from app.models.scene import Scene
from app.models.scene_marketplace import SceneListing
from app.models.scene_moderation import SceneListingReport, SceneListingAppeal


@pytest_asyncio.fixture
async def session(client):  # noqa: ARG001
    from app.db import engine
    Sess = async_sessionmaker(engine, expire_on_commit=False)
    async with Sess() as s:
        yield s


async def _make_scene(session: AsyncSession, org_id: UUID) -> Scene:
    scene = Scene(
        id=uuid4(), org_id=org_id, name=f"S-{uuid4().hex[:6]}",
        status="ready", n_gaussians=1_000,
    )
    session.add(scene)
    await session.commit()
    return scene


async def _make_listing(session: AsyncSession, org_id: UUID) -> SceneListing:
    scene = await _make_scene(session, org_id)
    listing = await market_svc.publish_scene(session, market_svc.PublishParams(
        scene_id=scene.id, org_id=org_id, publisher_user_id=uuid4(),
        title=f"Listing-{uuid4().hex[:6]}",
    ))
    await session.commit()
    return listing


# ---------- report basics ------------------------------------------------


@pytest.mark.asyncio
async def test_file_report_happy_path(session):
    seller_org = uuid4()
    reporter_org = uuid4()
    listing = await _make_listing(session, seller_org)

    report, hidden = await mod_svc.file_report(session, mod_svc.ReportParams(
        listing_id=listing.id,
        reporter_user_id=uuid4(),
        reporter_org_id=reporter_org,
        category="copyright",
        details="stolen from my drone shots",
    ))
    await session.commit()
    assert report.status == "open"
    assert report.category == "copyright"
    assert hidden is False  # single report doesn't hit threshold


@pytest.mark.asyncio
async def test_cannot_report_own_listing(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id,
            reporter_user_id=uuid4(),
            reporter_org_id=org,  # same org as listing owner
            category="spam",
        ))


@pytest.mark.asyncio
async def test_report_upsert_dedupes_per_user(session):
    seller = uuid4()
    reporter_org = uuid4()
    reporter_user = uuid4()
    listing = await _make_listing(session, seller)

    r1, _ = await mod_svc.file_report(session, mod_svc.ReportParams(
        listing_id=listing.id, reporter_user_id=reporter_user,
        reporter_org_id=reporter_org, category="spam",
    ))
    await session.commit()

    r2, _ = await mod_svc.file_report(session, mod_svc.ReportParams(
        listing_id=listing.id, reporter_user_id=reporter_user,
        reporter_org_id=reporter_org, category="privacy",
        details="updated reason",
    ))
    await session.commit()
    assert r1.id == r2.id  # upsert
    assert r2.category == "privacy"
    assert r2.details == "updated reason"


@pytest.mark.asyncio
async def test_report_unknown_category_rejected(session):
    listing = await _make_listing(session, uuid4())
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id, reporter_user_id=uuid4(),
            reporter_org_id=uuid4(), category="not-a-real-category",
        ))


# ---------- auto-hide threshold -------------------------------------------


@pytest.mark.asyncio
async def test_auto_hide_triggers_at_threshold(session):
    seller = uuid4()
    listing = await _make_listing(session, seller)

    hidden = False
    for i in range(mod_svc.AUTO_HIDE_THRESHOLD):
        _, hidden = await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id,
            reporter_user_id=uuid4(),
            reporter_org_id=uuid4(),
            category="sensitive_area",
        ))
        await session.commit()
    assert hidden is True

    fresh = (
        await session.execute(select(SceneListing).where(SceneListing.id == listing.id))
    ).scalar_one()
    assert fresh.status == "archived"


@pytest.mark.asyncio
async def test_auto_hide_ignores_soft_categories(session):
    seller = uuid4()
    listing = await _make_listing(session, seller)

    for _ in range(5):  # way over threshold
        _, hidden = await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id, reporter_user_id=uuid4(),
            reporter_org_id=uuid4(), category="spam",  # not auto-hide category
        ))
        await session.commit()
        assert hidden is False
    listing_now = (await session.execute(
        select(SceneListing).where(SceneListing.id == listing.id)
    )).scalar_one()
    assert listing_now.status == "active"


# ---------- resolve + rollup ----------------------------------------------


@pytest.mark.asyncio
async def test_resolve_report_accept_takes_down_and_rolls_up(session):
    seller = uuid4()
    listing = await _make_listing(session, seller)
    admin_id = uuid4()

    reports = []
    for _ in range(3):
        r, _ = await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id, reporter_user_id=uuid4(),
            reporter_org_id=uuid4(), category="illegal",
        ))
        reports.append(r)
    await session.commit()

    # Auto-hide already fired (threshold=3), status now 'archived'.
    # Move it back to active for the "take-down" transition test.
    from sqlalchemy import update
    await session.execute(update(SceneListing).where(SceneListing.id == listing.id).values(status="active"))
    await session.commit()

    resolved = await mod_svc.resolve_report(
        session, report_id=reports[0].id, resolver_user_id=admin_id,
        new_status="accepted", take_down_reason="verified illegal content",
    )
    await session.commit()
    assert resolved.status == "accepted"

    fresh_listing = (await session.execute(
        select(SceneListing).where(SceneListing.id == listing.id)
    )).scalar_one()
    assert fresh_listing.status == "removed"

    # Siblings should now be 'duplicate'
    sibs = (await session.execute(select(SceneListingReport).where(
        SceneListingReport.listing_id == listing.id,
        SceneListingReport.id != reports[0].id,
    ))).scalars().all()
    assert all(s.status == "duplicate" for s in sibs)


@pytest.mark.asyncio
async def test_resolve_report_accepted_requires_reason(session):
    listing = await _make_listing(session, uuid4())
    r, _ = await mod_svc.file_report(session, mod_svc.ReportParams(
        listing_id=listing.id, reporter_user_id=uuid4(),
        reporter_org_id=uuid4(), category="spam",
    ))
    await session.commit()
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.resolve_report(
            session, r.id, uuid4(),
            new_status="accepted",  # missing take_down_reason
        )


@pytest.mark.asyncio
async def test_report_summary_aggregation(session):
    listing = await _make_listing(session, uuid4())
    for cat in ["copyright", "copyright", "spam", "spam", "spam"]:
        await mod_svc.file_report(session, mod_svc.ReportParams(
            listing_id=listing.id, reporter_user_id=uuid4(),
            reporter_org_id=uuid4(), category=cat,
        ))
    await session.commit()
    summary = await mod_svc.report_summary_by_listing(session, listing.id)
    assert summary["total"] == 5
    assert summary["by_category"]["copyright"] == 2
    assert summary["by_category"]["spam"] == 3


# ---------- appeal --------------------------------------------------------


async def _remove_listing(session: AsyncSession, listing_id: UUID) -> None:
    await market_svc.moderate_listing(session, listing_id, "removed", reason="test")
    await session.commit()


@pytest.mark.asyncio
async def test_file_appeal_on_removed_listing(session):
    org = uuid4()
    user = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)

    appeal = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=user,
        appellant_org_id=org,
        appeal_message="This is my own footage of my factory floor",
    ))
    await session.commit()
    assert appeal.status == "pending"
    assert appeal.appeal_seq == 1


@pytest.mark.asyncio
async def test_appeal_rejected_when_listing_active(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.file_appeal(session, mod_svc.AppealParams(
            listing_id=listing.id, appellant_user_id=uuid4(),
            appellant_org_id=org, appeal_message="please review",
        ))


@pytest.mark.asyncio
async def test_appeal_only_publisher_org_allowed(session):
    seller_org = uuid4()
    other_org = uuid4()
    listing = await _make_listing(session, seller_org)
    await _remove_listing(session, listing.id)
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.file_appeal(session, mod_svc.AppealParams(
            listing_id=listing.id, appellant_user_id=uuid4(),
            appellant_org_id=other_org,
            appeal_message="I am not the owner",
        ))


@pytest.mark.asyncio
async def test_only_one_pending_appeal_per_listing(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="first appeal",
    ))
    await session.commit()
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.file_appeal(session, mod_svc.AppealParams(
            listing_id=listing.id, appellant_user_id=uuid4(),
            appellant_org_id=org, appeal_message="spam appeal",
        ))


@pytest.mark.asyncio
async def test_resolve_appeal_accept_restores_listing(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    appeal = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="please restore",
    ))
    await session.commit()

    resolved = await mod_svc.resolve_appeal(
        session, appeal.id, resolver_user_id=uuid4(),
        accept=True, note="approved after review",
    )
    await session.commit()
    assert resolved.status == "accepted"
    fresh = (await session.execute(
        select(SceneListing).where(SceneListing.id == listing.id)
    )).scalar_one()
    assert fresh.status == "active"


@pytest.mark.asyncio
async def test_resolve_appeal_reject_keeps_removed(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    appeal = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="please restore",
    ))
    await session.commit()

    resolved = await mod_svc.resolve_appeal(
        session, appeal.id, resolver_user_id=uuid4(),
        accept=False, note="the content is indeed non-compliant",
    )
    await session.commit()
    assert resolved.status == "rejected"
    fresh = (await session.execute(
        select(SceneListing).where(SceneListing.id == listing.id)
    )).scalar_one()
    assert fresh.status == "removed"


@pytest.mark.asyncio
async def test_withdraw_appeal(session):
    org = uuid4()
    user = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    appeal = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=user,
        appellant_org_id=org, appeal_message="I withdraw",
    ))
    await session.commit()

    withdrawn = await mod_svc.withdraw_appeal(
        session, appeal.id, actor_user_id=user, actor_org_id=org,
    )
    await session.commit()
    assert withdrawn.status == "withdrawn"


@pytest.mark.asyncio
async def test_appeal_seq_increments_on_reappeal(session):
    """Removal → withdraw appeal → re-remove → new appeal seq=2."""
    org = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    a1 = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="first",
    ))
    await session.commit()
    await mod_svc.withdraw_appeal(session, a1.id, uuid4(), org)
    await session.commit()
    # File a new appeal — the listing is still removed
    a2 = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="second",
    ))
    await session.commit()
    assert a1.appeal_seq == 1
    assert a2.appeal_seq == 2


@pytest.mark.asyncio
async def test_cannot_resolve_already_resolved_appeal(session):
    org = uuid4()
    listing = await _make_listing(session, org)
    await _remove_listing(session, listing.id)
    a = await mod_svc.file_appeal(session, mod_svc.AppealParams(
        listing_id=listing.id, appellant_user_id=uuid4(),
        appellant_org_id=org, appeal_message="msg",
    ))
    await session.commit()
    await mod_svc.resolve_appeal(session, a.id, uuid4(), accept=False)
    await session.commit()
    with pytest.raises(mod_svc.ModerationError):
        await mod_svc.resolve_appeal(session, a.id, uuid4(), accept=True)
