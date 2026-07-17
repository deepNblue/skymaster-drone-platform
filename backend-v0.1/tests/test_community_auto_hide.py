"""T6.8 — Community moderation auto-hide + admin stats.

Behavior under test:
* Once ``COMMUNITY_AUTO_HIDE_THRESHOLD`` (default 3) unique reporters
  file **open** reports against an approved post, the post silently
  transitions to ``pending`` with a machine-readable reason.
* When an admin resolves/dismisses enough reports to drop the open
  count below the threshold, an auto-hidden post is restored to
  ``approved`` — but only if it was auto-hidden, never admin-rejected.
* ``GET /api/v1/community/moderation/stats`` returns a fast summary
  for the admin dashboard.
"""
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


async def _new_post(client, tok, title="benign", body="benign body"):
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": body},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_auto_hide_after_threshold(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")

    author_tok, _ = await _mkuser("author@t68.com")
    r1_tok, _ = await _mkuser("r1@t68.com")
    r2_tok, _ = await _mkuser("r2@t68.com")
    r3_tok, _ = await _mkuser("r3@t68.com")

    post = await _new_post(client, author_tok)
    pid = post["id"]
    assert post["moderation_status"] == "approved"

    # Two reports — should still be approved.
    for tok in (r1_tok, r2_tok):
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201
    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(author_tok))
    assert r.status_code == 200
    assert r.json()["moderation_status"] == "approved"

    # Third report — trips the auto-hide.
    r = await client.post(
        f"/api/v1/community/posts/{pid}/report",
        json={"reason": "spam"},
        headers=_h(r3_tok),
    )
    assert r.status_code == 201

    # Author can still see own post; check via admin fetch to be canonical.
    admin_tok, _ = await _mkuser("admin@t68.com", role="admin")
    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.status_code == 200
    body = r.json()
    assert body["moderation_status"] == "pending"
    assert (body["moderation_reason"] or "").startswith("auto-hidden:")


@pytest.mark.asyncio
async def test_resolve_restores_auto_hidden_post(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "2")

    author_tok, _ = await _mkuser("author2@t68.com")
    r1_tok, _ = await _mkuser("rr1@t68.com")
    r2_tok, _ = await _mkuser("rr2@t68.com")
    admin_tok, _ = await _mkuser("admin2@t68.com", role="admin")

    post = await _new_post(client, author_tok, title="restore-me")
    pid = post["id"]

    for tok in (r1_tok, r2_tok):
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201

    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.json()["moderation_status"] == "pending"

    # Admin queue lists open reports.
    r = await client.get("/api/v1/community/moderation/reports", headers=_h(admin_tok))
    assert r.status_code == 200
    reports = r.json()["items"]
    assert len(reports) >= 2

    # Dismiss all open reports for this post.
    for rep in reports:
        if rep["post_id"] != pid:
            continue
        r = await client.post(
            f"/api/v1/community/moderation/reports/{rep['id']}/resolve",
            json={"action": "dismiss", "note": "false alarm"},
            headers=_h(admin_tok),
        )
        assert r.status_code == 200

    # Post should be restored to approved.
    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    body = r.json()
    assert body["moderation_status"] == "approved"
    assert body["moderation_reason"] is None


@pytest.mark.asyncio
async def test_admin_rejected_not_restored(client, monkeypatch):
    """If admin explicitly rejects, resolving reports must NOT re-promote."""
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "2")

    author_tok, _ = await _mkuser("author3@t68.com")
    r1_tok, _ = await _mkuser("rrr1@t68.com")
    r2_tok, _ = await _mkuser("rrr2@t68.com")
    admin_tok, _ = await _mkuser("admin3@t68.com", role="admin")

    post = await _new_post(client, author_tok, title="reject-sticky")
    pid = post["id"]

    for tok in (r1_tok, r2_tok):
        await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )

    # Admin hard-rejects the post.
    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "reject", "reason": "policy violation"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    assert r.json()["moderation_status"] == "rejected"

    # Resolve/dismiss reports.
    r = await client.get("/api/v1/community/moderation/reports", headers=_h(admin_tok))
    for rep in r.json()["items"]:
        if rep["post_id"] != pid:
            continue
        await client.post(
            f"/api/v1/community/moderation/reports/{rep['id']}/resolve",
            json={"action": "resolve"},
            headers=_h(admin_tok),
        )

    # Post should still be rejected — never silently un-rejected.
    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.json()["moderation_status"] == "rejected"


@pytest.mark.asyncio
async def test_moderation_stats_endpoint(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "5")

    admin_tok, _ = await _mkuser("adminS@t68.com", role="admin")
    author_tok, _ = await _mkuser("authorS@t68.com")
    reporter_tok, _ = await _mkuser("rptS@t68.com")

    post = await _new_post(client, author_tok, title="stats-post")
    await client.post(
        f"/api/v1/community/posts/{post['id']}/report",
        json={"reason": "spam"},
        headers=_h(reporter_tok),
    )

    r = await client.get(
        "/api/v1/community/moderation/stats", headers=_h(admin_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["auto_hide_threshold"] == 5
    assert body["open_reports"] >= 1
    assert "pending_posts" in body and "auto_hidden_posts" in body

    # Non-admin cannot access stats.
    r = await client.get(
        "/api/v1/community/moderation/stats", headers=_h(author_tok),
    )
    assert r.status_code in (401, 403)
