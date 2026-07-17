"""T6.23 — /community/tags top-N tag cloud."""
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


async def _seed_post(author_id, tags, moderation_status="approved"):
    from app.db import engine
    from app.models.community import CommunityPost
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CommunityPost(
            id=uuid4(), author_id=author_id,
            title="t", body="c", tags=tags,
            moderation_status=moderation_status,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_tag_cloud_frequency_order(client):
    tok, uid = await _mkuser("tc1@t623.com")
    await _seed_post(uid, ["python", "gis"])
    await _seed_post(uid, ["python", "flask"])
    await _seed_post(uid, ["python"])
    await _seed_post(uid, ["gis", "postgis"])

    r = await client.get("/api/v1/community/tags", headers=_h(tok))
    body = r.json()
    assert body["tags"]["python"] == 3
    assert body["tags"]["gis"] == 2
    assert body["tags"]["flask"] == 1
    assert body["tags"]["postgis"] == 1
    assert body["total_distinct"] == 4


@pytest.mark.asyncio
async def test_tag_cloud_ignores_non_approved(client):
    tok, uid = await _mkuser("tc2@t623.com")
    await _seed_post(uid, ["approved_tag"], moderation_status="approved")
    await _seed_post(uid, ["pending_tag"], moderation_status="pending")
    await _seed_post(uid, ["rejected_tag"], moderation_status="rejected")

    r = await client.get("/api/v1/community/tags", headers=_h(tok))
    tags = r.json()["tags"]
    assert "approved_tag" in tags
    assert "pending_tag" not in tags
    assert "rejected_tag" not in tags


@pytest.mark.asyncio
async def test_tag_cloud_limit(client):
    tok, uid = await _mkuser("tc3@t623.com")
    for i in range(5):
        await _seed_post(uid, [f"tag{i}"])
    r = await client.get(
        "/api/v1/community/tags", headers=_h(tok), params={"limit": 3},
    )
    body = r.json()
    assert len(body["tags"]) == 3
    assert body["total_distinct"] == 5
