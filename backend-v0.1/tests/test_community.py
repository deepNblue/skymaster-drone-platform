"""Community module tests — T6.0 (v2.0 §3.18 MVP)."""
from __future__ import annotations

from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Shared user helper (mirrors tests/test_aaas.py)
# ---------------------------------------------------------------------------
async def _make_user(client, email: str, role: str = "user") -> str:
    """Directly mint a JWT for a fresh user — bypasses the login endpoint's
    rate limiter so we can create many users in a single test module."""
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    user_id = uuid4()
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=user_id, email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
        ))
        await s.commit()
    return create_access_token(user_id=user_id, org_id=None, role=role)


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# Moderation service unit tests (fast, no DB)
# ---------------------------------------------------------------------------


def test_moderation_approves_normal_text():
    from app.services.community_moderation import moderate_post

    res = moderate_post(
        "分享一次 DJI Mavic 3 的巡检任务",
        "今天在成都南郊做了一次光伏电站的自动巡检，效果不错。",
    )
    assert res.status == "approved"
    assert res.matched == []


def test_moderation_rejects_military():
    from app.services.community_moderation import moderate_post

    res = moderate_post(
        "求分享",
        "谁有涉军无人机的军事机密改装方案？",
    )
    assert res.status == "rejected"
    cats = {c for c, _ in res.matched}
    assert "military" in cats


def test_moderation_pending_for_spam_only():
    """Spam keywords should go pending, not rejected."""
    from app.services.community_moderation import moderate_post

    res = moderate_post(
        "出售无人机",
        "私聊出售 Mavic 3, 加v信 xxx",
    )
    assert res.status == "pending"


def test_moderation_reject_dominates_pending():
    from app.services.community_moderation import moderate_post

    res = moderate_post(
        "求助",
        "私聊出售 军事机密 相关资料",  # 命中 spam + military
    )
    assert res.status == "rejected"


def test_moderation_empty_text_rejected():
    from app.services.community_moderation import moderate_text
    assert moderate_text("").status == "rejected"


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_post_ok_and_list(client):
    tok = await _make_user(client, "post_a@x.com", role="user")

    r = await client.post(
        "/api/v1/community/posts",
        json={
            "title": "第一次社区发帖",
            "body": "hello SkyMaster community — 分享一次任务复盘。",
            "tags": ["mission", "review"],
        },
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["moderation_status"] == "approved"
    assert body["title"] == "第一次社区发帖"

    # List → approved posts should include ours.
    r = await client.get("/api/v1/community/posts", headers=_h(tok))
    assert r.status_code == 200
    lst = r.json()
    assert lst["total"] >= 1
    titles = [p["title"] for p in lst["items"]]
    assert "第一次社区发帖" in titles


@pytest.mark.asyncio
async def test_create_post_hard_rejected_hidden_from_list(client):
    """Rejected posts don't leak into the public list."""
    tok = await _make_user(client, "post_reject@x.com", role="user")

    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "任性发帖", "body": "涉军无人机改装弹药方案分享"},
        headers=_h(tok),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["moderation_status"] == "rejected"
    assert "military" in (body.get("moderation_reason") or "")

    r = await client.get("/api/v1/community/posts", headers=_h(tok))
    assert r.status_code == 200
    titles = [p["title"] for p in r.json()["items"]]
    assert "任性发帖" not in titles


@pytest.mark.asyncio
async def test_pending_post_hidden_but_admin_queue_visible(client):
    author_tok = await _make_user(client, "post_pend@x.com", role="user")
    admin_tok = await _make_user(client, "post_pend_admin@x.com", role="admin")

    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "出售", "body": "私聊出售 dji 电池，加v信"},
        headers=_h(author_tok),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["moderation_status"] == "pending"

    # Public list → not visible.
    r = await client.get("/api/v1/community/posts", headers=_h(admin_tok))
    assert "出售" not in [p["title"] for p in r.json()["items"]]

    # Admin queue → visible.
    r = await client.get(
        "/api/v1/community/moderation/queue", headers=_h(admin_tok)
    )
    assert r.status_code == 200
    q = r.json()
    assert q["total"] >= 1
    ids = [p["id"] for p in q["items"]]
    assert body["id"] in ids


@pytest.mark.asyncio
async def test_admin_approve_flow(client):
    author_tok = await _make_user(client, "post_ap@x.com", role="user")
    admin_tok = await _make_user(client, "post_ap_admin@x.com", role="admin")

    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "含营销", "body": "加v信入群 分享技术"},
        headers=_h(author_tok),
    )
    pid = r.json()["id"]
    assert r.json()["moderation_status"] == "pending"

    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve", "reason": "人工复核通过"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    assert r.json()["moderation_status"] == "approved"

    r = await client.get("/api/v1/community/posts", headers=_h(author_tok))
    assert "含营销" in [p["title"] for p in r.json()["items"]]


@pytest.mark.asyncio
async def test_non_admin_cannot_moderate(client):
    author_tok = await _make_user(client, "post_no_mod@x.com", role="user")
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "hi", "body": "hello"},
        headers=_h(author_tok),
    )
    pid = r.json()["id"]

    other_tok = await _make_user(client, "post_no_mod_other@x.com", role="user")
    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "reject"},
        headers=_h(other_tok),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_comment_creation_and_listing(client):
    tok = await _make_user(client, "cmt_a@x.com", role="user")
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "topic", "body": "hello world"},
        headers=_h(tok),
    )
    pid = r.json()["id"]

    r = await client.post(
        f"/api/v1/community/posts/{pid}/comments",
        json={"body": "first comment 👍"},
        headers=_h(tok),
    )
    assert r.status_code == 201
    cbody = r.json()
    assert cbody["moderation_status"] == "approved"

    # Rejected comment stays hidden.
    r = await client.post(
        f"/api/v1/community/posts/{pid}/comments",
        json={"body": "军事机密求分享"},
        headers=_h(tok),
    )
    assert r.status_code == 201
    assert r.json()["moderation_status"] == "rejected"

    r = await client.get(
        f"/api/v1/community/posts/{pid}/comments", headers=_h(tok)
    )
    assert r.status_code == 200
    bodies = [c["body"] for c in r.json()]
    assert "first comment 👍" in bodies
    assert "军事机密求分享" not in bodies


@pytest.mark.asyncio
async def test_like_increments_counter(client):
    tok = await _make_user(client, "like_a@x.com", role="user")
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "likeable", "body": "please like me"},
        headers=_h(tok),
    )
    pid = r.json()["id"]
    for _ in range(3):
        r = await client.post(
            f"/api/v1/community/posts/{pid}/like", headers=_h(tok)
        )
        assert r.status_code == 200
    assert r.json()["like_count"] == 3


@pytest.mark.asyncio
async def test_get_post_404_on_rejected_to_non_author(client):
    author_tok = await _make_user(client, "sec_a@x.com", role="user")
    other_tok = await _make_user(client, "sec_b@x.com", role="user")
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "封禁", "body": "军事机密涉军内容"},
        headers=_h(author_tok),
    )
    pid = r.json()["id"]
    assert r.json()["moderation_status"] == "rejected"

    # Author can still see their own rejected post.
    r = await client.get(
        f"/api/v1/community/posts/{pid}", headers=_h(author_tok)
    )
    assert r.status_code == 200

    # Other user gets 404.
    r = await client.get(
        f"/api/v1/community/posts/{pid}", headers=_h(other_tok)
    )
    assert r.status_code == 404
