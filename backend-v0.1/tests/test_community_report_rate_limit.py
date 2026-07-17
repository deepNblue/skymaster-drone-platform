"""T6.10 — Community reporter rate-limit tests.

Same reporter must not spam more than N reports across the community
within a rolling window (default 5/24h, both env-configurable).
Existing rules — one report per (post, reporter), no self-report —
still apply and take precedence when they match.
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


async def _new_post(client, tok, title="p"):
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_report_rate_limit_blocks_after_max(client, monkeypatch):
    """5 reports allowed, 6th → 429."""
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "5")
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_WINDOW_HOURS", "24")
    # Ensure the auto-hide threshold doesn't fire (it doesn't rate-limit,
    # but we want a clean read of just the report result codes).
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "999")

    reporter_tok, _ = await _mkuser("r@t610.com")
    # 6 different authors → 6 different posts (avoids the per-post
    # uniqueness rule swallowing the test).
    post_ids = []
    for i in range(6):
        au_tok, _ = await _mkuser(f"au{i}@t610.com")
        post_ids.append(await _new_post(client, au_tok, title=f"p{i}"))

    for i, pid in enumerate(post_ids[:5]):
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(reporter_tok),
        )
        assert r.status_code == 201, f"report {i} unexpectedly failed: {r.text}"

    # 6th — must be rate-limited
    r = await client.post(
        f"/api/v1/community/posts/{post_ids[5]}/report",
        json={"reason": "spam"},
        headers=_h(reporter_tok),
    )
    assert r.status_code == 429, r.text
    assert "rate limit" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rate_limit_disabled_when_max_zero(client, monkeypatch):
    """Set MAX=0 → the whole feature is off, no matter how many posts."""
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "0")
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "999")

    reporter_tok, _ = await _mkuser("r0@t610.com")
    for i in range(8):
        au_tok, _ = await _mkuser(f"au0{i}@t610.com")
        pid = await _new_post(client, au_tok, title=f"p0{i}")
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(reporter_tok),
        )
        assert r.status_code == 201, f"iteration {i} blocked: {r.text}"


@pytest.mark.asyncio
async def test_rate_limit_scoped_per_reporter(client, monkeypatch):
    """Reporter A hitting the limit does NOT prevent reporter B from filing."""
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "2")
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "999")

    tok_a, _ = await _mkuser("rA@t610.com")
    tok_b, _ = await _mkuser("rB@t610.com")

    # 2 posts each — reporter A files on both, reporter B on both.
    posts = []
    for i in range(3):
        au_tok, _ = await _mkuser(f"authorAB{i}@t610.com")
        posts.append(await _new_post(client, au_tok, title=f"pab{i}"))

    for tok, code_expect in [(tok_a, 201), (tok_b, 201)]:
        for pid in posts[:2]:
            r = await client.post(
                f"/api/v1/community/posts/{pid}/report",
                json={"reason": "spam"},
                headers=_h(tok),
            )
            assert r.status_code == code_expect, (
                f"reporter={tok[:12]} pid={pid} → {r.status_code} {r.text}"
            )

    # A's 3rd → 429; B's 3rd → 429 too (their own bucket)
    for tok in (tok_a, tok_b):
        r = await client.post(
            f"/api/v1/community/posts/{posts[2]}/report",
            json={"reason": "spam"},
            headers=_h(tok),
        )
        assert r.status_code == 429


@pytest.mark.asyncio
async def test_duplicate_report_still_takes_precedence(client, monkeypatch):
    """When same reporter reports the SAME post twice, that's 409 (existing
    behavior). Rate limit must not silently mask that."""
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "5")
    monkeypatch.setenv("COMMUNITY_AUTO_HIDE_THRESHOLD", "999")

    reporter_tok, _ = await _mkuser("rdup@t610.com")
    au_tok, _ = await _mkuser("audup@t610.com")
    pid = await _new_post(client, au_tok, title="pdup")

    r = await client.post(
        f"/api/v1/community/posts/{pid}/report",
        json={"reason": "spam"},
        headers=_h(reporter_tok),
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/v1/community/posts/{pid}/report",
        json={"reason": "spam"},
        headers=_h(reporter_tok),
    )
    assert r.status_code == 409
