"""T6.21 — /community/me/reputation self-surface."""
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
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def _seed_report(reporter_id, status="resolved"):
    from app.db import engine
    from app.models.community import CommunityReport
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityReport(
            id=uuid4(),
            post_id=uuid4(),
            reporter_id=reporter_id,
            reason="spam",
            status=status,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_me_reputation_neutral_for_new_user(client):
    tok, _ = await _mkuser("me1@t621.com")
    r = await client.get("/api/v1/community/me/reputation", headers=_h(tok))
    body = r.json()
    assert body["resolved"] == 0
    assert body["dismissed"] == 0
    assert body["weight"] == 1.0
    assert body["label"] == "neutral"


@pytest.mark.asyncio
async def test_me_reputation_trusted_after_many_resolved(client):
    tok, uid = await _mkuser("me2@t621.com")
    # 3 resolved, 0 dismissed → weight = 1 + 0.2*3 = 1.6 → 'trusted'
    for _ in range(3):
        await _seed_report(uid, "resolved")
    r = await client.get("/api/v1/community/me/reputation", headers=_h(tok))
    body = r.json()
    assert body["resolved"] == 3
    assert body["dismissed"] == 0
    assert body["weight"] >= 1.4
    assert body["label"] == "trusted"


@pytest.mark.asyncio
async def test_me_reputation_suspect_after_many_dismissed(client):
    tok, uid = await _mkuser("me3@t621.com")
    # 0 resolved, 4 dismissed → weight = clamp(1 - 0.2*4, 0.3, 2.0) = 0.3
    for _ in range(4):
        await _seed_report(uid, "dismissed")
    r = await client.get("/api/v1/community/me/reputation", headers=_h(tok))
    body = r.json()
    assert body["dismissed"] == 4
    assert body["weight"] <= 0.6
    assert body["label"] == "suspect"


@pytest.mark.asyncio
async def test_me_reputation_scoped_to_caller(client):
    tok_a, uid_a = await _mkuser("me4a@t621.com")
    tok_b, uid_b = await _mkuser("me4b@t621.com")
    # A has 3 resolved reports; B has none
    for _ in range(3):
        await _seed_report(uid_a, "resolved")
    # A sees their own trust
    r = await client.get("/api/v1/community/me/reputation", headers=_h(tok_a))
    assert r.json()["resolved"] == 3
    # B still sees neutral 0/0
    r = await client.get("/api/v1/community/me/reputation", headers=_h(tok_b))
    assert r.json()["resolved"] == 0
    assert r.json()["label"] == "neutral"
