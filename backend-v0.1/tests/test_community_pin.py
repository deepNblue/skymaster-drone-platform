"""T6.14 — admin pin/unpin."""
from __future__ import annotations

from uuid import uuid4

import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email: str, role: str = "user"):
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


async def _mkpost(client, tok, title="p"):
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _approve(client, admin_tok, pid):
    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_pin_approved_post_succeeds(client):
    admin_tok, _ = await _mkuser("adm@t614.com", role="admin")
    author_tok, _ = await _mkuser("author@t614.com")

    pid = await _mkpost(client, author_tok, "pin-me")
    await _approve(client, admin_tok, pid)

    r = await client.post(
        f"/api/v1/community/posts/{pid}/pin",
        json={"pinned": True},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["pinned"] is True

    # Unpin round-trip
    r = await client.post(
        f"/api/v1/community/posts/{pid}/pin",
        json={"pinned": False},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    assert r.json()["pinned"] is False


@pytest.mark.asyncio
async def test_pin_rejects_non_admin(client):
    admin_tok, _ = await _mkuser("adm2@t614.com", role="admin")
    user_tok, _ = await _mkuser("user@t614.com")
    pid = await _mkpost(client, user_tok, "reg")
    await _approve(client, admin_tok, pid)

    r = await client.post(
        f"/api/v1/community/posts/{pid}/pin",
        json={"pinned": True},
        headers=_h(user_tok),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_pin_rejects_non_approved_post(client):
    admin_tok, _ = await _mkuser("adm3@t614.com", role="admin")
    author_tok, _ = await _mkuser("author2@t614.com")

    pid = await _mkpost(client, author_tok, "reject-me")
    # Explicitly reject so moderation_status != 'approved'
    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "reject", "reason": "test"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/community/posts/{pid}/pin",
        json={"pinned": True},
        headers=_h(admin_tok),
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_pin_missing_post_404(client):
    admin_tok, _ = await _mkuser("adm4@t614.com", role="admin")
    r = await client.post(
        f"/api/v1/community/posts/{uuid4()}/pin",
        json={"pinned": True},
        headers=_h(admin_tok),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pinned_posts_sort_first_in_feed(client):
    admin_tok, _ = await _mkuser("adm5@t614.com", role="admin")
    author_tok, _ = await _mkuser("author3@t614.com")

    a = await _mkpost(client, author_tok, "aaa")
    b = await _mkpost(client, author_tok, "bbb")
    c = await _mkpost(client, author_tok, "ccc")
    for pid in (a, b, c):
        await _approve(client, admin_tok, pid)

    # Pin 'c' (the newest) — expect it to jump to top
    r = await client.post(
        f"/api/v1/community/posts/{c}/pin",
        json={"pinned": True},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200

    r = await client.get("/api/v1/community/posts", headers=_h(author_tok))
    assert r.status_code == 200
    items = r.json()["items"]
    ids = [it["id"] for it in items]
    # Our three seeded posts appear; 'c' is above 'a' and 'b'.
    assert ids.index(c) < ids.index(a)
    assert ids.index(c) < ids.index(b)
