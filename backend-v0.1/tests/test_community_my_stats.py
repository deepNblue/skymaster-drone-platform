"""T6.22 — /community/me/stats."""
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


async def _seed_post(author_id, status="approved"):
    from app.db import engine
    from app.models.community import CommunityPost
    from sqlalchemy.ext.asyncio import async_sessionmaker
    pid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityPost(
            id=pid, author_id=author_id,
            title="t", body="c", tags=[], moderation_status=status,
        ))
        await s.commit()
    return pid


async def _seed_comment(author_id, post_id):
    from app.db import engine
    from app.models.community import CommunityComment
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityComment(
            id=uuid4(), post_id=post_id, author_id=author_id,
            body="reply body",
        ))
        await s.commit()


async def _seed_like(user_id, post_id):
    from app.db import engine
    from app.models.community import CommunityLike
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityLike(
            id=uuid4(), post_id=post_id, user_id=user_id,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_stats_zero_state(client):
    tok, _ = await _mkuser("m1@t622.com")
    r = await client.get("/api/v1/community/me/stats", headers=_h(tok))
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "posts_total": 0,
        "posts_by_status": {},
        "posts_approved": 0,
        "posts_pending": 0,
        "posts_rejected": 0,
        "comments_made": 0,
        "likes_given": 0,
        "likes_received": 0,
    }


@pytest.mark.asyncio
async def test_stats_post_status_grouping(client):
    tok, uid = await _mkuser("m2@t622.com")
    await _seed_post(uid, "approved")
    await _seed_post(uid, "approved")
    await _seed_post(uid, "pending")
    await _seed_post(uid, "rejected")

    r = await client.get("/api/v1/community/me/stats", headers=_h(tok))
    body = r.json()
    assert body["posts_total"] == 4
    assert body["posts_approved"] == 2
    assert body["posts_pending"] == 1
    assert body["posts_rejected"] == 1


@pytest.mark.asyncio
async def test_stats_comments_likes_and_inbound_likes(client):
    tok_a, uid_a = await _mkuser("m3a@t622.com")
    tok_b, uid_b = await _mkuser("m3b@t622.com")
    my_post = await _seed_post(uid_a, "approved")
    b_post = await _seed_post(uid_b, "approved")

    # I comment 2x on B's post
    await _seed_comment(uid_a, b_post)
    await _seed_comment(uid_a, b_post)
    # I like B's post
    await _seed_like(uid_a, b_post)
    # B likes my post twice — likes_received=1 assuming unique(user,post)
    await _seed_like(uid_b, my_post)

    r = await client.get("/api/v1/community/me/stats", headers=_h(tok_a))
    body = r.json()
    assert body["comments_made"] == 2
    assert body["likes_given"] == 1
    assert body["likes_received"] == 1
