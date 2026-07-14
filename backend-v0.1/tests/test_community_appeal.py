"""T6.16 — appeal against auto-hide."""
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


async def _seed_autohidden_post(client, author_tok, author_id, admin_tok, n_reports=3):
    """Create a post, approve, then flood with reports until T6.8/T6.11
    auto-hide flips it to 'pending'."""
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "controversial", "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(author_tok),
    )
    pid = r.json()["id"]
    await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    # Seed n distinct reporters
    for _ in range(n_reports):
        rep_tok, _ = await _mkuser("rep@t616.com")
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam", "detail": "auto-hide trigger"},
            headers=_h(rep_tok),
        )
        assert r.status_code == 201, r.text
    # Force auto-hide state (bypass threshold-tuning risk)
    from app.db import engine
    from app.models.community import CommunityPost
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import update
    from uuid import UUID as _U
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await s.execute(
            update(CommunityPost).where(CommunityPost.id == _U(pid)).values(
                moderation_status="pending",
                moderation_reason="auto-hidden: 3 open reports, weighted score=3.0",
            )
        )
        await s.commit()
    return pid


@pytest.mark.asyncio
async def test_author_can_appeal_autohidden_post(client):
    admin, _ = await _mkuser("adm@t616.com", role="admin")
    author, author_id = await _mkuser("author@t616.com")
    pid = await _seed_autohidden_post(client, author, author_id, admin)

    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={"note": "I did not spam"},
        headers=_h(author),
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_non_author_cannot_appeal(client):
    admin, _ = await _mkuser("adm2@t616.com", role="admin")
    author, author_id = await _mkuser("author2@t616.com")
    other, _ = await _mkuser("other@t616.com")

    pid = await _seed_autohidden_post(client, author, author_id, admin)
    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={},
        headers=_h(other),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_appeal_non_autohidden_post(client):
    admin, _ = await _mkuser("adm3@t616.com", role="admin")
    author, _ = await _mkuser("author3@t616.com")

    # Not auto-hidden — just approve and leave alone
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "clean", "body": "hi"},
        headers=_h(author),
    )
    pid = r.json()["id"]
    await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin),
    )
    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={},
        headers=_h(author),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_overturn_restores_post_and_dismisses_reports(client):
    admin, _ = await _mkuser("adm4@t616.com", role="admin")
    author, author_id = await _mkuser("author4@t616.com")
    pid = await _seed_autohidden_post(client, author, author_id, admin)

    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={"note": "false positive"},
        headers=_h(author),
    )
    aid = r.json()["id"]

    r = await client.post(
        f"/api/v1/community/moderation/appeals/{aid}/resolve",
        json={"action": "overturn", "review_note": "OK to restore"},
        headers=_h(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "overturned"

    # Post restored
    r = await client.get(
        f"/api/v1/community/posts/{pid}", headers=_h(author),
    )
    assert r.status_code == 200
    assert r.json()["moderation_status"] == "approved"

    # Open reports should now be 'dismissed'
    r = await client.get(
        "/api/v1/community/moderation/reports?status=dismissed",
        headers=_h(admin),
    )
    assert r.status_code == 200
    dismissed = [
        rep for rep in r.json()["items"] if rep["post_id"] == pid
    ]
    assert len(dismissed) >= 3


@pytest.mark.asyncio
async def test_uphold_keeps_hidden_no_side_effects(client):
    admin, _ = await _mkuser("adm5@t616.com", role="admin")
    author, author_id = await _mkuser("author5@t616.com")
    pid = await _seed_autohidden_post(client, author, author_id, admin)

    r = await client.post(
        f"/api/v1/community/posts/{pid}/appeal",
        json={},
        headers=_h(author),
    )
    aid = r.json()["id"]

    r = await client.post(
        f"/api/v1/community/moderation/appeals/{aid}/resolve",
        json={"action": "uphold"},
        headers=_h(admin),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "upheld"

    # Post still pending; open reports untouched
    r = await client.get(
        f"/api/v1/community/posts/{pid}", headers=_h(author),
    )
    assert r.json()["moderation_status"] == "pending"


@pytest.mark.asyncio
async def test_only_one_pending_appeal_per_post(client):
    admin, _ = await _mkuser("adm6@t616.com", role="admin")
    author, author_id = await _mkuser("author6@t616.com")
    pid = await _seed_autohidden_post(client, author, author_id, admin)

    r1 = await client.post(
        f"/api/v1/community/posts/{pid}/appeal", json={}, headers=_h(author),
    )
    assert r1.status_code == 201

    r2 = await client.post(
        f"/api/v1/community/posts/{pid}/appeal", json={}, headers=_h(author),
    )
    assert r2.status_code == 409
