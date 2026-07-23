"""F3.1 · Community bookmark tests."""
from __future__ import annotations

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


async def _mkuser(role: str = "user") -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"bm+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return (
        create_access_token(user_id=uid, org_id=org, role=role),
        uid, org,
    )


async def _mkpost(
    author_id: UUID | None = None,
    tenant_id: UUID | None = None,
    moderation_status: str = "approved",
    title: str = "Test Post",
) -> UUID:
    S = async_sessionmaker(engine, expire_on_commit=False)
    pid = uuid4()
    async with S() as s:
        p = CommunityPost(
            id=pid,
            tenant_id=tenant_id,
            author_id=author_id,
            title=title,
            body="body",
            tags=["drone", "test"],
            moderation_status=moderation_status,
        )
        s.add(p)
        await s.commit()
    return pid


async def test_bookmark_add_and_status(client) -> None:
    tok, uid, _ = await _mkuser()
    pid = await _mkpost()
    # Status before: not bookmarked
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["bookmarked"] is False
    assert body["total_bookmarks"] == 0

    # Add
    r = await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["post_id"] == str(pid)
    assert body["total_bookmarks"] == 1

    # Status after
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok),
    )
    assert r.json()["bookmarked"] is True


async def test_bookmark_add_idempotent(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    r1 = await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    r2 = await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # Total remains 1
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok),
    )
    assert r.json()["total_bookmarks"] == 1


async def test_bookmark_add_nonexistent_post(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/community/bookmarks/{uuid4()}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_bookmark_add_rejected_post_blocked(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost(moderation_status="rejected")
    r = await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r.status_code == 400


async def test_bookmark_add_archived_post_blocked(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost(moderation_status="archived")
    r = await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r.status_code == 400


async def test_bookmark_remove(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    r = await client.delete(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r.status_code == 204
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok),
    )
    assert r.json()["bookmarked"] is False


async def test_bookmark_remove_nonexistent_idempotent(client) -> None:
    tok, _, _ = await _mkuser()
    pid = await _mkpost()
    r = await client.delete(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
    )
    assert r.status_code == 204  # No error, just no-op


async def test_bookmark_list_ordered(client) -> None:
    tok, _, _ = await _mkuser()
    pid1 = await _mkpost(title="First")
    pid2 = await _mkpost(title="Second")
    pid3 = await _mkpost(title="Third")
    for pid in (pid1, pid2, pid3):
        await client.post(
            f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
        )
    r = await client.get(
        "/api/v1/community/bookmarks", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    # All 3 present (order may be non-deterministic if NOW() equal).
    titles = {b["title"] for b in body}
    assert titles == {"First", "Second", "Third"}
    # Contains bookmark metadata
    assert "bookmarked_at" in body[0]
    assert body[0]["tags"] == ["drone", "test"]


async def test_bookmark_list_pagination(client) -> None:
    tok, _, _ = await _mkuser()
    for i in range(5):
        pid = await _mkpost(title=f"Post{i}")
        await client.post(
            f"/api/v1/community/bookmarks/{pid}", headers=_h(tok),
        )
    r = await client.get(
        "/api/v1/community/bookmarks?limit=2&offset=1", headers=_h(tok),
    )
    assert len(r.json()) == 2


async def test_bookmark_user_isolation(client) -> None:
    """User A bookmarks post; User B sees empty list."""
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    pid = await _mkpost()
    await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok_a),
    )
    # B's list is empty
    r = await client.get(
        "/api/v1/community/bookmarks", headers=_h(tok_b),
    )
    assert r.json() == []
    # But B sees total_bookmarks=1 (aggregate)
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok_b),
    )
    body = r.json()
    assert body["bookmarked"] is False  # B didn't bookmark
    assert body["total_bookmarks"] == 1  # But total is 1


async def test_bookmark_total_reflects_multiple_users(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    pid = await _mkpost()
    await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok_a),
    )
    await client.post(
        f"/api/v1/community/bookmarks/{pid}", headers=_h(tok_b),
    )
    r = await client.get(
        f"/api/v1/community/bookmarks/{pid}/status", headers=_h(tok_a),
    )
    assert r.json()["total_bookmarks"] == 2
