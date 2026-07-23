"""T7.13 — batch second-approval."""
from __future__ import annotations

from uuid import uuid4

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


async def _seed_pending_second(client, tok, org_id, title="hi-risk"):
    """Create a high-risk approval that lands in pending_second_approval."""
    from app.db import engine
    from app.models.flight_approval import FlightApproval
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from datetime import datetime, timedelta, timezone
    aid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(FlightApproval(
            id=aid,
            tenant_id=org_id,
            title=title,
            purpose="commercial-mapping",
            category="specific",
            area_polygon=[
                [113.0, 22.5], [113.01, 22.5],
                [113.01, 22.51], [113.0, 22.51], [113.0, 22.5],
            ],
            max_alt_m=200,  # >120m => triggers high-risk
            start_ts=datetime.now(timezone.utc) + timedelta(days=1),
            end_ts=datetime.now(timezone.utc) + timedelta(days=1, hours=2),
            requires_second_approval=True,
            status="pending_second_approval",
            timeline=[],
        ))
        await s.commit()
    return aid


@pytest.mark.asyncio
async def test_batch_approve_supervisor_ok(client):
    sup_tok, _, org_id = await _mkuser("sup@t713.com", role="supervisor")
    a1 = await _seed_pending_second(client, sup_tok, org_id, "a1")
    a2 = await _seed_pending_second(client, sup_tok, org_id, "a2")

    r = await client.post(
        "/api/v1/approvals/batch-second-approval",
        json={
            "approval_ids": [str(a1), str(a2)],
            "decision": "approve",
            "note": "batch OK",
            "aircraft_weight_kg": 25.0,
        },
        headers=_h(sup_tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] == 2, body


@pytest.mark.asyncio
async def test_batch_reject_returns_to_draft(client):
    sup_tok, _, org_id = await _mkuser("sup2@t713.com", role="supervisor")
    a1 = await _seed_pending_second(client, sup_tok, org_id, "r1")
    a2 = await _seed_pending_second(client, sup_tok, org_id, "r2")

    r = await client.post(
        "/api/v1/approvals/batch-second-approval",
        json={
            "approval_ids": [str(a1), str(a2)],
            "decision": "reject",
            "note": "insufficient info",
        },
        headers=_h(sup_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rejected"] == 2
    assert body["approved"] == 0


@pytest.mark.asyncio
async def test_batch_regular_user_denied(client):
    user_tok, _, org_id = await _mkuser("user@t713.com", role="user")
    a1 = await _seed_pending_second(client, user_tok, org_id, "d1")

    r = await client.post(
        "/api/v1/approvals/batch-second-approval",
        json={
            "approval_ids": [str(a1)],
            "decision": "approve",
        },
        headers=_h(user_tok),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_batch_partial_success_on_wrong_status(client):
    sup_tok, _, org_id = await _mkuser("sup3@t713.com", role="supervisor")
    ok_id = await _seed_pending_second(client, sup_tok, org_id, "ok")

    # Manually set second to 'draft' to simulate the wrong status
    from app.db import engine
    from app.models.flight_approval import FlightApproval
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import update
    from uuid import UUID as _U
    bad_id = await _seed_pending_second(client, sup_tok, org_id, "bad")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await s.execute(update(FlightApproval).where(
            FlightApproval.id == _U(str(bad_id))
        ).values(status="draft"))
        await s.commit()

    r = await client.post(
        "/api/v1/approvals/batch-second-approval",
        json={
            "approval_ids": [str(ok_id), str(bad_id)],
            "decision": "approve",
            "aircraft_weight_kg": 25.0,
        },
        headers=_h(sup_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] == 1
    assert body["failed"] == 1
    bad_result = next(x for x in body["results"] if x["approval_id"] == str(bad_id))
    assert bad_result["ok"] is False
    assert "not pending_second_approval" in bad_result["error"]
