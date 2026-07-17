"""T6.11 — reporter reputation weighting for auto-hide."""
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
    """Create a post. Community moderation auto-approves clean content
    (see community_moderation.moderate_post), so the returned post is
    already 'approved' and eligible for auto-hide."""
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    assert r.json()["moderation_status"] == "approved", r.text
    return r.json()["id"]


async def _seed_reputation(client, admin_tok, reporter_tok, *, resolves: int, dismisses: int):
    """Give a reporter a history of `resolves` resolved + `dismisses` dismissed
    reports so their weight moves off 1.0."""
    # Each event needs its own post because a reporter can only report each
    # post once.
    unrelated_author, _ = await _mkuser(f"histauthor-{uuid4().hex[:6]}@t611.com")
    for i, action in enumerate(["resolve"] * resolves + ["dismiss"] * dismisses):
        pid = await _mkpost(client, unrelated_author, title=f"hist-{i}")
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(reporter_tok),
        )
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        r = await client.post(
            f"/api/v1/community/moderation/reports/{rid}/resolve",
            json={"action": action, "note": f"seed-{i}"},
            headers=_h(admin_tok),
        )
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_high_reputation_reporter_triggers_hide_faster(client, monkeypatch):
    """A reporter with 5 resolved / 0 dismissed → weight 2.0.
    Two of them → weighted score 4.0 ≥ threshold=3 → auto-hide fires
    even though the naive count is 2 < 3.
    """
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")
    monkeypatch.setenv("COMMUNITY_REPORT_WEIGHTED", "1")
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "999")  # avoid rate limit

    admin_tok, _ = await _mkuser("adm@t611.com", role="admin")
    r_a_tok, _ = await _mkuser("hi-rep-a@t611.com")
    r_b_tok, _ = await _mkuser("hi-rep-b@t611.com")

    # Give each reporter a 5-resolve history → weight = 1 + 0.2*5 = 2.0
    await _seed_reputation(client, admin_tok, r_a_tok, resolves=5, dismisses=0)
    await _seed_reputation(client, admin_tok, r_b_tok, resolves=5, dismisses=0)

    author_tok, _ = await _mkuser("target-au@t611.com")
    pid = await _mkpost(client, author_tok, title="target")

    # Two reports from the two high-rep users → weighted 4.0 → auto-hide
    for tok in (r_a_tok, r_b_tok):
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201

    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.status_code == 200
    body = r.json()
    assert body["moderation_status"] == "pending", body
    assert "weighted score=" in body.get("moderation_reason", "")


@pytest.mark.asyncio
async def test_low_reputation_reporters_delay_hide(client, monkeypatch):
    """3 reporters all with 5 dismissed / 0 resolved → each weight = 0.3.
    Weighted score = 0.9 < threshold=3 → naive count of 3 would have
    triggered auto-hide, but with reputation weighting it doesn't."""
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")
    monkeypatch.setenv("COMMUNITY_REPORT_WEIGHTED", "1")
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "999")

    admin_tok, _ = await _mkuser("adm2@t611.com", role="admin")
    reporters = []
    for i in range(3):
        tok, _ = await _mkuser(f"lo-rep-{i}@t611.com")
        await _seed_reputation(client, admin_tok, tok,
                               resolves=0, dismisses=5)
        reporters.append(tok)

    author_tok, _ = await _mkuser("target2-au@t611.com")
    pid = await _mkpost(client, author_tok, title="target2")

    for tok in reporters:
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201, r.text

    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.status_code == 200
    # Naive count=3 would auto-hide; weighted=0.9 keeps it approved
    assert r.json()["moderation_status"] == "approved"


@pytest.mark.asyncio
async def test_disable_weighting_reverts_to_count(client, monkeypatch):
    """COMMUNITY_REPORT_WEIGHTED=0 → old count-based behavior."""
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "3")
    monkeypatch.setenv("COMMUNITY_REPORT_WEIGHTED", "0")
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "999")

    admin_tok, _ = await _mkuser("adm3@t611.com", role="admin")
    reporters = []
    for i in range(3):
        tok, _ = await _mkuser(f"nowt-{i}@t611.com")
        # Even with dismissed history, MAX=0 reverts to naive count
        await _seed_reputation(client, admin_tok, tok,
                               resolves=0, dismisses=5)
        reporters.append(tok)

    author_tok, _ = await _mkuser("target3-au@t611.com")
    pid = await _mkpost(client, author_tok, title="target3")

    for tok in reporters:
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 201

    r = await client.get(f"/api/v1/community/posts/{pid}", headers=_h(admin_tok))
    assert r.json()["moderation_status"] == "pending"
