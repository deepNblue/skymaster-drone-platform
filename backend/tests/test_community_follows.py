"""F3.3 · Community follow tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.community import CommunityPost
from app.models.user import User
from app.services.auth import create_access_token, hash_password


pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(
    email_prefix: str = "fl",
) -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"{email_prefix}+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return (
        create_access_token(user_id=uid, org_id=org, role="user"),
        uid, org,
    )


async def _mkpost(
    author_id: UUID,
    *, title: str = "P",
    moderation_status: str = "approved",
    created_at: datetime | None = None,
) -> UUID:
    S = async_sessionmaker(engine, expire_on_commit=False)
    pid = uuid4()
    async with S() as s:
        p = CommunityPost(
            id=pid, title=title, body="b",
            tags=["drone"],
            moderation_status=moderation_status,
            author_id=author_id,
        )
        if created_at is not None:
            p.created_at = created_at
        s.add(p)
        await s.commit()
    return pid


# ========== Follow / Unfollow ==========

async def test_follow_creates_relationship(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    r = await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["following"] is True
    assert body["followed_id"] == str(uid_b)

    # status
    r = await client.get(
        f"/api/v1/community/follows/{uid_b}/status", headers=_h(tok_a),
    )
    assert r.json()["following"] is True


async def test_follow_idempotent(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    r1 = await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    r2 = await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201


async def test_follow_self_rejected(client) -> None:
    tok, uid, _ = await _mkuser("s")
    r = await client.post(
        f"/api/v1/community/follows/{uid}", headers=_h(tok),
    )
    assert r.status_code == 400


async def test_follow_missing_user_404(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/community/follows/{uuid4()}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_unfollow(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    r = await client.delete(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    assert r.status_code == 204
    r = await client.get(
        f"/api/v1/community/follows/{uid_b}/status", headers=_h(tok_a),
    )
    assert r.json()["following"] is False


async def test_unfollow_idempotent(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    r = await client.delete(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    assert r.status_code == 204


# ========== Lists / Counts ==========

async def test_lists_and_counts(client) -> None:
    tok_a, uid_a, _ = await _mkuser("a")
    tok_b, uid_b, _ = await _mkuser("b")
    _tok_c, uid_c, _ = await _mkuser("c")
    # A follows B, C
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    await client.post(
        f"/api/v1/community/follows/{uid_c}", headers=_h(tok_a),
    )
    # B also follows A (mutual)
    await client.post(
        f"/api/v1/community/follows/{uid_a}", headers=_h(tok_b),
    )
    # A's counts: following=2, followers=1
    r = await client.get(
        "/api/v1/community/follows/me/counts", headers=_h(tok_a),
    )
    body = r.json()
    assert body["following"] == 2
    assert body["followers"] == 1

    # A's following list has B and C
    r = await client.get(
        "/api/v1/community/follows/me/following", headers=_h(tok_a),
    )
    ids = {row["user_id"] for row in r.json()}
    assert ids == {str(uid_b), str(uid_c)}

    # A's followers list has B only
    r = await client.get(
        "/api/v1/community/follows/me/followers", headers=_h(tok_a),
    )
    ids = {row["user_id"] for row in r.json()}
    assert ids == {str(uid_b)}


# ========== Feed ==========

async def test_feed_returns_followed_posts(client) -> None:
    tok_a, _uid_a, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    _tok_c, uid_c, _ = await _mkuser("c")
    now = datetime.now(timezone.utc)

    # A follows B (not C)
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )

    b_post = await _mkpost(
        uid_b, title="from B",
        created_at=now - timedelta(hours=1),
    )
    _c_post = await _mkpost(
        uid_c, title="from C",
        created_at=now - timedelta(hours=1),
    )

    r = await client.get(
        "/api/v1/community/follows/feed", headers=_h(tok_a),
    )
    assert r.status_code == 200
    body = r.json()
    titles = [x["title"] for x in body]
    assert "from B" in titles
    assert "from C" not in titles
    assert body[0]["post_id"] == str(b_post)


async def test_feed_excludes_rejected_and_stale(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    now = datetime.now(timezone.utc)
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    await _mkpost(
        uid_b, title="fresh",
        created_at=now - timedelta(hours=2),
    )
    await _mkpost(
        uid_b, title="rejected", moderation_status="rejected",
        created_at=now - timedelta(hours=1),
    )
    await _mkpost(
        uid_b, title="stale",
        created_at=now - timedelta(hours=800),
    )
    r = await client.get(
        "/api/v1/community/follows/feed?within_hours=168",
        headers=_h(tok_a),
    )
    titles = {x["title"] for x in r.json()}
    assert "fresh" in titles
    assert "rejected" not in titles
    assert "stale" not in titles


async def test_feed_empty_when_not_following_anyone(client) -> None:
    tok, _, _ = await _mkuser("lonely")
    r = await client.get(
        "/api/v1/community/follows/feed", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_feed_pagination(client) -> None:
    tok_a, _, _ = await _mkuser("a")
    _tok_b, uid_b, _ = await _mkuser("b")
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    now = datetime.now(timezone.utc)
    for i in range(5):
        await _mkpost(
            uid_b, title=f"P{i}",
            created_at=now - timedelta(hours=i + 1),
        )
    r = await client.get(
        "/api/v1/community/follows/feed?limit=2&offset=1",
        headers=_h(tok_a),
    )
    assert len(r.json()) == 2
