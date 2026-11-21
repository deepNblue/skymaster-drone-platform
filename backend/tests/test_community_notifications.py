"""F3.4 · Community notification tests."""
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


async def _mkuser(prefix: str = "n") -> tuple[str, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"{prefix}+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid


async def _mkpost(author_id: UUID) -> UUID:
    S = async_sessionmaker(engine, expire_on_commit=False)
    pid = uuid4()
    async with S() as s:
        s.add(CommunityPost(
            id=pid, title="P", body="b", tags=["drone"],
            moderation_status="approved", author_id=author_id,
        ))
        await s.commit()
    return pid


# ================ Emit via follow ================

async def test_follow_emits_new_follower_notification(client) -> None:
    tok_a, uid_a = await _mkuser("a")
    tok_b, uid_b = await _mkuser("b")
    r = await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    assert r.status_code == 201
    # B should see 1 unread new_follower
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_b),
    )
    assert r.json()["unread"] == 1

    r = await client.get(
        "/api/v1/community/notifications",
        headers=_h(tok_b),
    )
    items = r.json()
    assert len(items) == 1
    assert items[0]["kind"] == "new_follower"
    assert items[0]["actor_id"] == str(uid_a)
    assert items[0]["read"] is False


async def test_repeated_follow_deduped(client) -> None:
    tok_a, _ = await _mkuser("a")
    tok_b, uid_b = await _mkuser("b")
    for _ in range(3):
        await client.post(
            f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
        )
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_b),
    )
    # dedupe collapses repeats while unread
    assert r.json()["unread"] == 1


async def test_no_self_notification_on_self_follow_attempt(
    client,
) -> None:
    tok, uid = await _mkuser("s")
    # Self-follow fails 400, so shouldn't emit either
    await client.post(
        f"/api/v1/community/follows/{uid}", headers=_h(tok),
    )
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok),
    )
    assert r.json()["unread"] == 0


# ================ Emit via like ================

async def test_like_emits_post_liked_notification(client) -> None:
    tok_author, uid_author = await _mkuser("author")
    tok_liker, uid_liker = await _mkuser("liker")
    pid = await _mkpost(uid_author)

    r = await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok_liker),
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/community/notifications",
        headers=_h(tok_author),
    )
    items = r.json()
    assert len(items) == 1
    assert items[0]["kind"] == "post_liked"
    assert items[0]["post_id"] == str(pid)
    assert items[0]["actor_id"] == str(uid_liker)


async def test_self_like_does_not_notify(client) -> None:
    tok, uid = await _mkuser("author")
    pid = await _mkpost(uid)
    await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok),
    )
    # Author liking own post → no self-notification
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok),
    )
    assert r.json()["unread"] == 0


async def test_like_twice_deduped(client) -> None:
    tok_a, uid_a = await _mkuser("a")
    tok_liker, _ = await _mkuser("l")
    pid = await _mkpost(uid_a)
    for _ in range(3):
        await client.post(
            f"/api/v1/community/likes/{pid}", headers=_h(tok_liker),
        )
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_a),
    )
    assert r.json()["unread"] == 1


# ================ Read / mark-read ================

async def test_mark_single_read(client) -> None:
    tok_a, _ = await _mkuser("a")
    tok_b, uid_b = await _mkuser("b")
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    r = await client.get(
        "/api/v1/community/notifications", headers=_h(tok_b),
    )
    nid = r.json()[0]["id"]

    r = await client.post(
        f"/api/v1/community/notifications/{nid}/read",
        headers=_h(tok_b),
    )
    assert r.status_code == 200

    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_b),
    )
    assert r.json()["unread"] == 0


async def test_mark_read_wrong_user_404(client) -> None:
    tok_a, _ = await _mkuser("a")
    tok_b, uid_b = await _mkuser("b")
    tok_c, _ = await _mkuser("c")
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    r = await client.get(
        "/api/v1/community/notifications", headers=_h(tok_b),
    )
    nid = r.json()[0]["id"]
    # C tries to mark B's notification as read
    r = await client.post(
        f"/api/v1/community/notifications/{nid}/read",
        headers=_h(tok_c),
    )
    assert r.status_code == 404


async def test_mark_all_read(client) -> None:
    tok_target, uid_target = await _mkuser("t")
    for i in range(3):
        tok_f, _ = await _mkuser(f"f{i}")
        await client.post(
            f"/api/v1/community/follows/{uid_target}",
            headers=_h(tok_f),
        )
    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_target),
    )
    assert r.json()["unread"] == 3

    r = await client.post(
        "/api/v1/community/notifications/read-all",
        headers=_h(tok_target),
    )
    assert r.json()["updated"] == 3

    r = await client.get(
        "/api/v1/community/notifications/unread-count",
        headers=_h(tok_target),
    )
    assert r.json()["unread"] == 0


async def test_mark_all_read_by_kind(client) -> None:
    tok_author, uid_author = await _mkuser("author")
    tok_actor, _ = await _mkuser("actor")
    # Generate 1 follow + 1 like notification
    await client.post(
        f"/api/v1/community/follows/{uid_author}",
        headers=_h(tok_actor),
    )
    pid = await _mkpost(uid_author)
    await client.post(
        f"/api/v1/community/likes/{pid}", headers=_h(tok_actor),
    )

    r = await client.get(
        "/api/v1/community/notifications/unread-summary",
        headers=_h(tok_author),
    )
    body = r.json()
    assert body["new_follower"] == 1
    assert body["post_liked"] == 1
    assert body["total"] == 2

    # Mark only follows as read
    r = await client.post(
        "/api/v1/community/notifications/read-all"
        "?kinds=new_follower",
        headers=_h(tok_author),
    )
    assert r.json()["updated"] == 1

    r = await client.get(
        "/api/v1/community/notifications/unread-summary",
        headers=_h(tok_author),
    )
    body = r.json()
    assert body["new_follower"] == 0
    assert body["post_liked"] == 1


# ================ Filters ================

async def test_list_only_unread_filter(client) -> None:
    tok_a, _ = await _mkuser("a")
    tok_b, uid_b = await _mkuser("b")
    await client.post(
        f"/api/v1/community/follows/{uid_b}", headers=_h(tok_a),
    )
    # Mark all read
    await client.post(
        "/api/v1/community/notifications/read-all",
        headers=_h(tok_b),
    )
    r = await client.get(
        "/api/v1/community/notifications?only_unread=true",
        headers=_h(tok_b),
    )
    assert r.json() == []
    r = await client.get(
        "/api/v1/community/notifications",
        headers=_h(tok_b),
    )
    assert len(r.json()) == 1  # still visible in history


async def test_unread_summary_default_zeros(client) -> None:
    tok, _ = await _mkuser("z")
    r = await client.get(
        "/api/v1/community/notifications/unread-summary",
        headers=_h(tok),
    )
    body = r.json()
    for k in ("new_follower", "post_liked", "post_reply", "mention"):
        assert body[k] == 0
    assert body["total"] == 0
