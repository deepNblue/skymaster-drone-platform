"""T6.19 — trending posts endpoint."""
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
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def _seed_post(title, like_count=0, comment_count=0,
                     age_hours=0, pinned=False, status="approved"):
    from app.db import engine
    from app.models.community import CommunityPost
    from sqlalchemy.ext.asyncio import async_sessionmaker

    pid = uuid4()
    author_id = uuid4()
    when = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        p = CommunityPost(
            id=pid,
            title=title,
            body="x",
            author_id=author_id,
            like_count=like_count,
            comment_count=comment_count,
            pinned=pinned,
            moderation_status=status,
            created_at=when,
        )
        s.add(p)
        await s.commit()
    return pid


@pytest.mark.asyncio
async def test_trending_orders_by_hotness(client):
    tok, _ = await _mkuser("t619a@sky.dev")
    # A: 5 likes, 0 comments → hotness = 10
    # B: 2 likes, 8 comments → hotness = 12
    # C: 10 likes, 0 comments → hotness = 20 (winner)
    a = await _seed_post("A", like_count=5)
    b = await _seed_post("B", like_count=2, comment_count=8)
    c = await _seed_post("C", like_count=10)
    r = await client.get(
        "/api/v1/community/posts/trending",
        headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()["items"]]
    # Only assert relative order of our seed posts
    my = [i for i in ids if i in {str(a), str(b), str(c)}]
    assert my == [str(c), str(b), str(a)]


@pytest.mark.asyncio
async def test_trending_excludes_pending_and_pinned(client):
    tok, _ = await _mkuser("t619b@sky.dev")
    ok = await _seed_post("ok", like_count=3)
    pending = await _seed_post("pend", like_count=99, status="pending")
    pinned = await _seed_post("pinned", like_count=99, pinned=True)
    r = await client.get(
        "/api/v1/community/posts/trending",
        headers=_h(tok),
    )
    ids = {x["id"] for x in r.json()["items"]}
    assert str(ok) in ids
    assert str(pending) not in ids
    assert str(pinned) not in ids


@pytest.mark.asyncio
async def test_trending_respects_window_hours(client):
    tok, _ = await _mkuser("t619c@sky.dev")
    fresh = await _seed_post("fresh", like_count=1)
    stale = await _seed_post("stale", like_count=99, age_hours=72)
    # Default 24h window: stale (72h old) is filtered out even w/ 99 likes
    r = await client.get(
        "/api/v1/community/posts/trending",
        headers=_h(tok),
    )
    ids = {x["id"] for x in r.json()["items"]}
    assert str(fresh) in ids
    assert str(stale) not in ids
    # Widen the window to 168h → stale reappears at the top
    r = await client.get(
        "/api/v1/community/posts/trending",
        params={"window_hours": 168},
        headers=_h(tok),
    )
    items = r.json()["items"]
    subset = [x["id"] for x in items if x["id"] in {str(stale), str(fresh)}]
    assert subset == [str(stale), str(fresh)]
