"""T6.6 tests — daily usage rollup for Model Marketplace dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest


async def _make_user(email: str, role: str = "user", *, org_id=None):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def _make_org(name="Org"):
    from app.db import engine
    from app.models.organization import Organization
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    oid = uuid4()
    async with S() as s:
        s.add(Organization(id=oid, name=f"{name}-{uuid4().hex[:4]}"))
        await s.commit()
    return oid


async def _seed_dep_with_events(
    org_id: UUID, *, quota=None, events=(),
) -> UUID:
    """Build listing + version + deployment + events. `events` is a
    sequence of (days_ago, outcome, units)."""
    from app.db import engine
    from app.models.model_marketplace import (
        ModelDeployment, ModelListing, ModelUsageEvent, ModelVersion,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        listing = ModelListing(
            slug=f"mm-{uuid4().hex[:6]}",
            name="Daily rollup test",
            task="detection",
            framework="onnx",
            visibility="public",
        )
        s.add(listing)
        await s.flush()
        ver = ModelVersion(
            listing_id=listing.id, version="1.0.0",
            artifact_uri="s3://x", artifact_sha256="c" * 64,
            review_status="approved",
        )
        s.add(ver)
        await s.flush()
        dep = ModelDeployment(
            org_id=org_id,
            listing_id=listing.id,
            version_id=ver.id,
            status="installed",
            quota_calls_per_day=quota,
        )
        s.add(dep)
        await s.flush()
        now = datetime.now(timezone.utc)
        for days_ago, outcome, units in events:
            s.add(ModelUsageEvent(
                deployment_id=dep.id,
                units=units,
                unit_type="call",
                outcome=outcome,
                created_at=now - timedelta(days=days_ago),
            ))
        await s.commit()
        return dep.id


@pytest.mark.asyncio
async def test_usage_daily_backfills_and_groups(client):
    org = await _make_org()
    tok, _ = await _make_user("mm_daily_user@x.com", org_id=org)
    dep_id = await _seed_dep_with_events(
        org,
        quota=1000,
        events=[
            (0, "ok", 3),         # today
            (0, "error", 1),      # today
            (1, "ok", 5),         # yesterday
            (5, "ok", 2),         # 5 days ago
            (25, "ok", 100),      # outside default 7d window
        ],
    )
    r = await client.get(
        f"/api/v1/model-marketplace/deployments/{dep_id}/usage-daily?since_days=7",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_calls_per_day"] == 1000
    assert body["since_days"] == 7
    points = body["points"]
    # 7-day window inclusive of today = 8 backfilled points.
    assert 7 <= len(points) <= 9
    total = sum(p["total_units"] for p in points)
    assert total == 3 + 1 + 5 + 2  # 25-day-ago event excluded
    # Each point has by_outcome dict; zero days are backfilled.
    zeroed = [p for p in points if p["total_units"] == 0]
    assert len(zeroed) >= 3
    # Today's bucket has both ok+error.
    latest = points[-1]
    assert latest["by_outcome"].get("ok", 0) == 3
    assert latest["by_outcome"].get("error", 0) == 1


@pytest.mark.asyncio
async def test_usage_daily_cross_org_403(client):
    org_a = await _make_org("A")
    org_b = await _make_org("B")
    _, _ = await _make_user("mm_own@x.com", org_id=org_a)
    tok_b, _ = await _make_user("mm_intruder@x.com", org_id=org_b)
    dep_id = await _seed_dep_with_events(org_a, events=[(0, "ok", 1)])
    r = await client.get(
        f"/api/v1/model-marketplace/deployments/{dep_id}/usage-daily",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_usage_daily_missing_deployment_404(client):
    tok, _ = await _make_user("mm_404@x.com")
    r = await client.get(
        f"/api/v1/model-marketplace/deployments/{uuid4()}/usage-daily",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 404
