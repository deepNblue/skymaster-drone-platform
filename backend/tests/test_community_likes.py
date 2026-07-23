"""F3.2 · Community like + trending tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.community import CommunityPost
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.community_like import compute_hot_score

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"lk+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _mkpost(
    *, moderation_status: str = "approved",
    title: str = "P", tenant_id: UUID | None = None,
    like_count: int = 0, view_count: int = 0,
    comment_count: int = 0,
    created_at: datetime | None = None,
) -> UUID:
    S = async_sessionmaker(engine, expire_on_commit=False)
    pid = uuid4()
    async with S() as s:
        p = CommunityPost(
            id=pid, title=title, body="b",
            tags=["drone"],
            moderation_status=moderation_status,
            tenant_id=tenant_id,
            like_count=like_count,
            view_count=view_count,
            comment_count=comment_count,
        )
        if created_at is not None:
            p.created_at = created_at
        s.add(p)
        await s.commit()
    return pid


# ================ hot_score pure math ================

def test_hot_score_zero_engagement_zero() -> None:
    assert compute_hot_score(0, 0, 0, 1) == 0.0


def test_hot_score_decays_with_age() -> None:
    fresh = compute_hot_score(10, 100, 5, age_hours=0)
    aged = compute_hot_score(10, 100, 5, age_hours=24)
    # 24h = 1 half-life → aged ≈ fresh / 2
    assert 0.4 < (aged / fresh) < 0.6


def test_hot_score_likes_outrank_views() -> None:
    likes_only = compute_hot_score(10, 0, 0, age_hours=1)
    views_only = compute_hot_score(0, 10, 0, age_hours=1)
    assert likes_only > views_only * 3


def test_hot_score_engagement_monotonic() -> None:
    a = compute_hot_score(5, 10, 2, age_hours=5)
    b = compute_hot_score(50, 10, 2, age_hours=5)
    assert b > a


def test_hot_score_never_negative_for_negative_age() -> None:
    s = compute_hot_score(10, 10, 1, age_hours=-5)
    assert s > 0  # treats age<0 as 0


# ================ REST: like/unlike ================

async def test_like_add_and_status(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    # Before
    r = await client.get(
        f"/api/v1/community/likes/{pid}/status", headers=_h(tok),
    )
    body = r.json()
    assert body["liked"] is False
    assert body["like_count"] == 0

    # Add
    r = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["liked"] is True
    assert body["like_count"] == 1

    # Status after
    r = await client.get(
        f"/api/v1/community/likes/{pid}/status", headers=_h(tok),
    )
    assert r.json()["liked"] is True


async def test_like_idempotent(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    r1 = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    r2 = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    assert r1.json()["like_count"] == 1
    assert r2.json()["like_count"] == 1


async def test_like_unlike_flow(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    r = await client.delete(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["liked"] is False
    assert body["like_count"] == 0


async def test_like_unlike_idempotent(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    r = await client.delete(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["like_count"] == 0


async def test_like_nonexistent_post(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/community/likes/{uuid4()}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_like_rejected_post(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost(moderation_status="rejected")
    r = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    assert r.status_code == 400


async def test_like_multi_user_count(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    pid = await _mkpost()
    r = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok_a),
    )
    assert r.json()["like_count"] == 1
    r = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok_b),
    )
    assert r.json()["like_count"] == 2
    # B unlikes → 1
    r = await client.delete(
        f"/api/v1/community/likes/{pid}", headers=_h(tok_b),
    )
    assert r.json()["like_count"] == 1


# ================ REST: trending ================

async def test_trending_orders_by_hot_score(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    # 3 posts, all recent
    cold = await _mkpost(
        title="cold", like_count=0, view_count=5,
        comment_count=0, created_at=now - timedelta(hours=6),
    )
    warm = await _mkpost(
        title="warm", like_count=5, view_count=20,
        comment_count=3, created_at=now - timedelta(hours=3),
    )
    hot = await _mkpost(
        title="hot", like_count=50, view_count=200,
        comment_count=10, created_at=now - timedelta(hours=1),
    )
    r = await client.get(
        "/api/v1/community/trending?within_hours=24",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    titles = [p["title"] for p in body]
    # 'hot' should rank first, cold last
    assert titles[0] == "hot"
    assert "cold" in titles
    assert body[0]["hot_score"] > body[-1]["hot_score"]
    # Check fields present
    assert "age_hours" in body[0]
    assert body[0]["like_count"] == 50


async def test_trending_excludes_rejected_and_out_of_window(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    approved = await _mkpost(
        title="ok", like_count=10,
        created_at=now - timedelta(hours=2),
    )
    await _mkpost(
        title="rejected", moderation_status="rejected",
        like_count=999,
        created_at=now - timedelta(hours=1),
    )
    await _mkpost(
        title="stale", like_count=999,
        created_at=now - timedelta(hours=200),
    )
    r = await client.get(
        "/api/v1/community/trending?within_hours=72",
        headers=_h(tok),
    )
    titles = [p["title"] for p in r.json()]
    assert "ok" in titles
    assert "rejected" not in titles
    assert "stale" not in titles


async def test_trending_tenant_scope(client) -> None:
    tok_a, _, org_a = await _mkuser()
    tok_b, _, _org_b = await _mkuser()
    now = datetime.now(timezone.utc)
    await _mkpost(
        title="a-post", like_count=5, tenant_id=org_a,
        created_at=now - timedelta(hours=1),
    )
    await _mkpost(
        title="b-post", like_count=100, tenant_id=uuid4(),
        created_at=now - timedelta(hours=1),
    )
    # tenant_scope=false → sees both
    r = await client.get(
        "/api/v1/community/trending", headers=_h(tok_a),
    )
    titles = {p["title"] for p in r.json()}
    assert "a-post" in titles
    assert "b-post" in titles
    # tenant_scope=true → only sees a-post
    r = await client.get(
        "/api/v1/community/trending?tenant_scope=true",
        headers=_h(tok_a),
    )
    titles = {p["title"] for p in r.json()}
    assert titles == {"a-post"}


async def test_trending_limit(client) -> None:
    tok, _, _ = await _mkuser()
    for i in range(5):
        await _mkpost(title=f"P{i}", like_count=i)
    r = await client.get(
        "/api/v1/community/trending?limit=3", headers=_h(tok),
    )
    assert len(r.json()) == 3


async def test_trending_empty(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/community/trending", headers=_h(tok),
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
