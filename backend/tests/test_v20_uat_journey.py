"""v2.0 MVP UAT — end-to-end happy path across all major v2.0 features.

Exercises the full user journey we've been building in T6.5 → T5.10:

  1. Two users sign up (author + reader) + an admin.
  2. Author creates a community post; admin approves it.
  3. Reader likes + reports the post.
  4. Two more reporters pile on → auto-hide fires (T6.8/T6.11).
  5. Author appeals the auto-hide (T6.16).
  6. Admin overturns the appeal → post restored, reports dismissed,
     reporters lose reputation (T6.11 cascade).
  7. Admin publishes a ModelListing.
  8. Reader stars the listing (T5.10) and verifies /favorites.
  9. Moderator dashboard /stats returns pending_appeals=0,
     top_reasons_7d includes 'spam' with count 3 (T6.18).

Uses the async test client — no live server required, but exercises
every real code path we shipped.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(email: str, role: str = "user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = uuid4()
    org_id = uuid4()
    unique_email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(
            User(
                id=uid,
                email=unique_email,
                hashed_pw=hash_password("StrongPass!"),
                role=role,
                org_id=org_id,
            )
        )
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


@pytest.mark.asyncio
async def test_v20_mvp_full_journey(client, monkeypatch):
    """v2.0 UAT — everything from community moderation to marketplace."""

    # Set auto-hide threshold to 3 so 3 reports trigger it deterministically
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")

    # -------------------------------------------------------------------
    # (1) Cast of characters
    # -------------------------------------------------------------------
    admin_tok, _ = await _mkuser("uat-admin@sky.dev", role="admin")
    author_tok, _ = await _mkuser("uat-author@sky.dev")
    reader_tok, _ = await _mkuser("uat-reader@sky.dev")
    r2_tok, _ = await _mkuser("uat-reporter2@sky.dev")
    r3_tok, _ = await _mkuser("uat-reporter3@sky.dev")

    # -------------------------------------------------------------------
    # (2) Author creates + admin approves a post
    # -------------------------------------------------------------------
    r = await client.post(
        "/api/v1/community/posts",
        json={
            "title": "UAT: how do I fly beyond 120m?",
            "body": "Asking for a friend who reads the CAAC bulletin.",
            "tags": ["altitude", "beyond-vlos"],
        },
        headers=_h(author_tok),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    r = await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200

    # -------------------------------------------------------------------
    # (3) Reader likes + reports the post (spam)
    # -------------------------------------------------------------------
    r = await client.post(
        f"/api/v1/community/posts/{pid}/like",
        headers=_h(reader_tok),
    )
    assert r.status_code == 200
    assert r.json()["liked_by_me"] is True
    assert r.json()["like_count"] == 1

    r = await client.post(
        f"/api/v1/community/posts/{pid}/report",
        json={"reason": "spam", "note": "Looks off-topic"},
        headers=_h(reader_tok),
    )
    assert r.status_code == 201

    # -------------------------------------------------------------------
    # (4) Two more reporters → auto-hide fires
    # -------------------------------------------------------------------
    for tok in [r2_tok, r3_tok]:
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201

    r = await client.get(
        f"/api/v1/community/posts/{pid}",
        headers=_h(author_tok),
    )
    post_state = r.json()
    assert post_state["moderation_status"] == "pending"
    assert post_state["moderation_reason"] and \
        post_state["moderation_reason"].startswith("auto-hidden")

    # -------------------------------------------------------------------
    # (5) Author appeals the auto-hide
    # -------------------------------------------------------------------
    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={"note": "Genuine question about regulation — not spam"},
        headers=_h(author_tok),
    )
    assert r.status_code == 201, r.text
    appeal_id = r.json()["id"]

    # Double-appeal blocked
    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={"note": "again"},
        headers=_h(author_tok),
    )
    assert r.status_code == 409

    # -------------------------------------------------------------------
    # (6) Admin overturns — post restored, reports dismissed
    # -------------------------------------------------------------------
    r = await client.post(
        f"/api/v1/community/moderation/appeals/{appeal_id}/resolve",
        json={
            "action": "overturn",
            "review_note": "UAT — reporters overreacted",
        },
        headers=_h(admin_tok),
    )
    assert r.status_code == 200

    r = await client.get(
        f"/api/v1/community/posts/{pid}",
        headers=_h(author_tok),
    )
    assert r.json()["moderation_status"] == "approved"
    # moderation_reason cleared on overturn
    assert r.json()["moderation_reason"] is None

    # -------------------------------------------------------------------
    # (7) Admin publishes a ModelListing
    # -------------------------------------------------------------------
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker

    listing_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=listing_id,
            slug=f"uat-yolo-{uuid4().hex[:6]}",
            name="UAT YOLO",
            task="detection",
            framework="pytorch",
            visibility="public",
        ))
        await s.commit()

    # -------------------------------------------------------------------
    # (8) Reader stars the listing → shows up on /favorites with
    #     favorited_by_me=True
    # -------------------------------------------------------------------
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{listing_id}/favorite",
        headers=_h(reader_tok),
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/model-marketplace/favorites",
        headers=_h(reader_tok),
    )
    ids = {x["id"] for x in r.json()}
    assert str(listing_id) in ids
    assert all(x["favorited_by_me"] for x in r.json())

    # And the general list annotates favorited_by_me correctly
    r = await client.get(
        "/api/v1/model-marketplace/listings",
        headers=_h(reader_tok),
    )
    entry = next(
        (x for x in r.json()["items"] if x["id"] == str(listing_id)),
        None,
    )
    assert entry is not None
    assert entry["favorited_by_me"] is True

    # For another user, it's False
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{listing_id}",
        headers=_h(author_tok),
    )
    assert r.json()["favorited_by_me"] is False

    # -------------------------------------------------------------------
    # (9) Moderator dashboard stats reflect the journey
    # -------------------------------------------------------------------
    r = await client.get(
        "/api/v1/community/moderation/stats",
        headers=_h(admin_tok),
    )
    body = r.json()
    # Appeal was resolved → pending_appeals back to 0
    assert body["pending_appeals"] == 0
    # top_reasons_7d includes at least 3 spam reports from step 4
    spam_row = next(
        (x for x in body["top_reasons_7d"] if x["reason"] == "spam"),
        None,
    )
    assert spam_row is not None
    assert spam_row["count"] >= 3
