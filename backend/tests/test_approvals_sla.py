"""T8.2 — /approvals/summary/sla."""
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


async def _seed(tenant, status, created_ago_h=0, decided_ago_h=None):
    """decided_ago_h=None → updated_at = created_at (i.e. no decision)."""
    from app.db import engine
    from app.models.flight_approval import FlightApproval
    from sqlalchemy.ext.asyncio import async_sessionmaker
    aid = uuid4()
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(hours=created_ago_h)
    updated_at = (
        now - timedelta(hours=decided_ago_h)
        if decided_ago_h is not None else created_at
    )
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(FlightApproval(
            id=aid, tenant_id=tenant, created_by=uuid4(), status=status,
            title="t", pilot_name="p", aircraft_model="m",
            area_polygon=[[104, 30]], max_alt_m=100,
            start_ts=now, end_ts=now + timedelta(hours=1),
            created_at=created_at, updated_at=updated_at,
        ))
        await s.commit()
    return aid


@pytest.mark.asyncio
async def test_sla_avg_decision_hours(client):
    tok, _, org = await _mkuser("sla1@t82.com")
    # 3 decided: 2h, 4h, 6h → avg = 4h
    await _seed(org, "approved", created_ago_h=10, decided_ago_h=8)
    await _seed(org, "approved", created_ago_h=10, decided_ago_h=6)
    await _seed(org, "rejected", created_ago_h=10, decided_ago_h=4)

    r = await client.get("/api/v1/approvals/summary/sla", headers=_h(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["decided_last_30d"] == 3
    assert abs(body["avg_decision_hours"] - 4.0) < 0.1


@pytest.mark.asyncio
async def test_sla_pending_over_24h_and_72h(client):
    tok, _, org = await _mkuser("sla2@t82.com")
    await _seed(org, "submitted", created_ago_h=5)   # under 24h
    await _seed(org, "submitted", created_ago_h=30)  # >24h
    await _seed(org, "under_review", created_ago_h=80)  # >72h
    await _seed(org, "draft", created_ago_h=100)     # not open — ignored

    r = await client.get("/api/v1/approvals/summary/sla", headers=_h(tok))
    body = r.json()
    assert body["pending_over_24h"] == 2  # both 30h + 80h
    assert body["pending_over_72h"] == 1


@pytest.mark.asyncio
async def test_sla_zero_state(client):
    tok, _, org = await _mkuser("sla3@t82.com")
    r = await client.get("/api/v1/approvals/summary/sla", headers=_h(tok))
    body = r.json()
    assert body == {
        "decided_last_30d": 0,
        "avg_decision_hours": 0.0,
        "p95_decision_hours": 0.0,
        "pending_over_24h": 0,
        "pending_over_72h": 0,
    }
