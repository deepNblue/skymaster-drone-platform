"""T8.1 — /approvals/summary dashboard counters."""
from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email, role="user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    uid = uuid4()
    org_id = uuid4()
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid, org_id


async def _seed_approval(tenant_id, status="draft", age_days=0):
    from app.db import engine
    from app.models.flight_approval import FlightApproval
    from sqlalchemy.ext.asyncio import async_sessionmaker
    aid = uuid4()
    when = datetime.now(timezone.utc) - timedelta(days=age_days)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(FlightApproval(
            id=aid,
            tenant_id=tenant_id,
            created_by=uuid4(),
            status=status,
            title="test approval",
            purpose="uat",
            pilot_name="pilot",
            aircraft_model="Mavic",
            area_polygon=[[104, 30], [104.1, 30], [104.1, 30.1], [104, 30]],
            max_alt_m=100,
            start_ts=datetime.now(timezone.utc),
            end_ts=datetime.now(timezone.utc) + timedelta(hours=1),
            created_at=when,
        ))
        await s.commit()
    return aid


@pytest.mark.asyncio
async def test_summary_counts_by_status(client):
    tok, _, org = await _mkuser("sm1@t81.com")
    await _seed_approval(org, status="draft")
    await _seed_approval(org, status="draft")
    await _seed_approval(org, status="submitted")
    await _seed_approval(org, status="under_review")
    await _seed_approval(org, status="approved")

    r = await client.get(
        "/api/v1/approvals/summary", headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status_counts"]["draft"] == 2
    assert body["status_counts"]["submitted"] == 1
    assert body["status_counts"]["under_review"] == 1
    assert body["status_counts"]["approved"] == 1
    assert body["in_flight"] == 2  # submitted + under_review
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_summary_last_7d_excludes_older(client):
    tok, _, org = await _mkuser("sm2@t81.com")
    await _seed_approval(org, age_days=1)   # in window
    await _seed_approval(org, age_days=3)   # in window
    await _seed_approval(org, age_days=10)  # excluded

    r = await client.get(
        "/api/v1/approvals/summary", headers=_h(tok),
    )
    body = r.json()
    assert body["submitted_last_7d"] == 2
    assert body["total"] == 3


@pytest.mark.asyncio
async def test_summary_scoped_to_tenant(client):
    t1, _, org1 = await _mkuser("sm3a@t81.com")
    t2, _, org2 = await _mkuser("sm3b@t81.com")
    await _seed_approval(org1, status="draft")
    await _seed_approval(org1, status="draft")
    await _seed_approval(org2, status="approved")

    r = await client.get(
        "/api/v1/approvals/summary", headers=_h(t1),
    )
    assert r.json()["total"] == 2
    r = await client.get(
        "/api/v1/approvals/summary", headers=_h(t2),
    )
    assert r.json()["total"] == 1
