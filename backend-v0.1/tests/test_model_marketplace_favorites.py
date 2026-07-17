"""T5.10 — model marketplace favorites (bookmarks)."""
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


async def _seed_listing():
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    lid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=lid,
            slug=f"star-{uuid4().hex[:6]}",
            name="Star Model",
            task="detection",
            framework="pytorch",
            visibility="public",
        ))
        await s.commit()
    return lid


@pytest.mark.asyncio
async def test_star_and_unstar_roundtrip(client):
    tok, _ = await _mkuser("s1@t510.com")
    lid = await _seed_listing()

    # Not yet starred
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(tok),
    )
    assert r.json()["favorited_by_me"] is False

    # Star
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/favorite",
        headers=_h(tok),
    )
    assert r.status_code == 201
    assert r.json()["favorited"] is True

    # Idempotent second call
    r2 = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/favorite",
        headers=_h(tok),
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == r.json()["id"]

    # favorited_by_me on detail
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(tok),
    )
    assert r.json()["favorited_by_me"] is True

    # Unstar
    r = await client.delete(
        f"/api/v1/model-marketplace/listings/{lid}/favorite",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["favorited"] is False

    # Idempotent unstar
    r = await client.delete(
        f"/api/v1/model-marketplace/listings/{lid}/favorite",
        headers=_h(tok),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_list_my_favorites(client):
    tok, _ = await _mkuser("s2@t510.com")
    a = await _seed_listing()
    b = await _seed_listing()
    c = await _seed_listing()

    # Star only a and c
    for lid in [a, c]:
        r = await client.post(
            f"/api/v1/model-marketplace/listings/{lid}/favorite",
            headers=_h(tok),
        )
        assert r.status_code == 201

    r = await client.get(
        "/api/v1/model-marketplace/favorites", headers=_h(tok),
    )
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert ids == {str(a), str(c)}
    assert all(x["favorited_by_me"] is True for x in r.json())


@pytest.mark.asyncio
async def test_favorited_by_me_per_caller(client):
    """Two users, one stars — the other should see False."""
    t1, _ = await _mkuser("s3a@t510.com")
    t2, _ = await _mkuser("s3b@t510.com")
    lid = await _seed_listing()

    await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/favorite",
        headers=_h(t1),
    )
    r1 = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(t1),
    )
    r2 = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(t2),
    )
    assert r1.json()["favorited_by_me"] is True
    assert r2.json()["favorited_by_me"] is False


@pytest.mark.asyncio
async def test_star_missing_listing_returns_404(client):
    tok, _ = await _mkuser("s4@t510.com")
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{uuid4()}/favorite",
        headers=_h(tok),
    )
    assert r.status_code == 404
