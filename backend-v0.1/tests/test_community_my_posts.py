"""T6.20 — GET /posts/mine (author-scoped, all-status)."""
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


async def _seed_post(author_id, title, status="approved"):
    from app.db import engine
    from app.models.community import CommunityPost
    from sqlalchemy.ext.asyncio import async_sessionmaker
    pid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityPost(
            id=pid, title=title, body="x",
            author_id=author_id, moderation_status=status,
        ))
        await s.commit()
    return pid


@pytest.mark.asyncio
async def test_mine_returns_all_statuses_scoped_to_caller(client):
    tok_a, uid_a = await _mkuser("mine-a@t620.com")
    tok_b, uid_b = await _mkuser("mine-b@t620.com")

    a_ok = await _seed_post(uid_a, "A approved", "approved")
    a_pending = await _seed_post(uid_a, "A pending", "pending")
    a_rej = await _seed_post(uid_a, "A rejected", "rejected")
    _ = await _seed_post(uid_b, "B approved", "approved")

    # Caller A sees only their own posts, across all statuses
    r = await client.get(
        "/api/v1/community/posts/mine",
        headers=_h(tok_a),
    )
    assert r.status_code == 200, r.text
    ids = {x["id"] for x in r.json()["items"]}
    assert ids == {str(a_ok), str(a_pending), str(a_rej)}

    # status_filter narrows it
    r = await client.get(
        "/api/v1/community/posts/mine",
        params={"status_filter": "pending"},
        headers=_h(tok_a),
    )
    ids = {x["id"] for x in r.json()["items"]}
    assert ids == {str(a_pending)}


@pytest.mark.asyncio
async def test_mine_rejects_bad_status_filter(client):
    tok, _ = await _mkuser("mine-bad@t620.com")
    r = await client.get(
        "/api/v1/community/posts/mine",
        params={"status_filter": "banana"},
        headers=_h(tok),
    )
    assert r.status_code == 400
