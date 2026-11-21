"""T6.15 — idempotent like + real unlike."""
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
    return create_access_token(user_id=uid, org_id=org_id, role=role)


async def _mkpost_approved(auth_client, author_tok, admin_tok, title="p"):
    r = await auth_client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(author_tok),
    )
    pid = r.json()["id"]
    r = await auth_client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    return pid


@pytest.mark.asyncio
async def test_like_is_idempotent(auth_client):
    admin = await _mkuser("adm@t615.com", role="admin")
    author = await _mkuser("author@t615.com")
    liker = await _mkuser("liker@t615.com")

    pid = await _mkpost_approved(auth_client, author, admin, "idem")

    # Like x3 → count stays at 1
    for _ in range(3):
        r = await auth_client.post(
            f"/api/v1/community/posts/{pid}/like",
            headers=_h(liker),
        )
        assert r.status_code == 200
    assert r.json()["like_count"] == 1


@pytest.mark.asyncio
async def test_unlike_undoes_like(auth_client):
    admin = await _mkuser("adm2@t615.com", role="admin")
    author = await _mkuser("author2@t615.com")
    liker = await _mkuser("liker2@t615.com")

    pid = await _mkpost_approved(auth_client, author, admin, "u")
    await auth_client.post(f"/api/v1/community/posts/{pid}/like", headers=_h(liker))

    r = await auth_client.delete(
        f"/api/v1/community/posts/{pid}/like", headers=_h(liker),
    )
    assert r.status_code == 200
    assert r.json()["like_count"] == 0


@pytest.mark.asyncio
async def test_unlike_when_not_liked_is_noop(auth_client):
    admin = await _mkuser("adm3@t615.com", role="admin")
    author = await _mkuser("author3@t615.com")
    other = await _mkuser("other@t615.com")

    pid = await _mkpost_approved(auth_client, author, admin, "noop")

    r = await auth_client.delete(
        f"/api/v1/community/posts/{pid}/like", headers=_h(other),
    )
    assert r.status_code == 200
    assert r.json()["like_count"] == 0


@pytest.mark.asyncio
async def test_multi_user_likes_stack(auth_client):
    admin = await _mkuser("adm4@t615.com", role="admin")
    author = await _mkuser("author4@t615.com")
    u1 = await _mkuser("u1@t615.com")
    u2 = await _mkuser("u2@t615.com")
    u3 = await _mkuser("u3@t615.com")

    pid = await _mkpost_approved(auth_client, author, admin, "stack")

    for tok in (u1, u2, u3):
        r = await auth_client.post(
            f"/api/v1/community/posts/{pid}/like", headers=_h(tok),
        )
        assert r.status_code == 200
    assert r.json()["like_count"] == 3

    # One unlikes → 2
    r = await auth_client.delete(
        f"/api/v1/community/posts/{pid}/like", headers=_h(u2),
    )
    assert r.json()["like_count"] == 2
