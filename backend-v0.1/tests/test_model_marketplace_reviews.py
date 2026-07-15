"""T5.11 — model marketplace reviews."""
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
            slug=f"rv-{uuid4().hex[:6]}",
            name="Reviewable",
            task="detection",
            framework="pytorch",
            visibility="public",
        ))
        await s.commit()
    return lid


@pytest.mark.asyncio
async def test_create_and_list_reviews(client):
    t1, _ = await _mkuser("rv1@t511.com")
    t2, _ = await _mkuser("rv2@t511.com")
    lid = await _seed_listing()

    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        json={"rating": 5, "comment": "excellent"},
        headers=_h(t1),
    )
    assert r.status_code == 201
    assert r.json()["rating"] == 5

    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        json={"rating": 3, "comment": "meh"},
        headers=_h(t2),
    )
    assert r.status_code == 201

    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        headers=_h(t1),
    )
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert {x["rating"] for x in r.json()} == {5, 3}


@pytest.mark.asyncio
async def test_review_is_upsert_not_duplicate(client):
    tok, _ = await _mkuser("rv-up@t511.com")
    lid = await _seed_listing()

    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        json={"rating": 5},
        headers=_h(tok),
    )
    assert r.status_code == 201
    review_id = r.json()["id"]

    # Second call from same user — updates rather than duplicates
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        json={"rating": 2, "comment": "changed my mind"},
        headers=_h(tok),
    )
    assert r.status_code == 201
    assert r.json()["id"] == review_id
    assert r.json()["rating"] == 2

    # Only one row
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        headers=_h(tok),
    )
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_aggregate_and_listing_out_average(client):
    t1, _ = await _mkuser("a1@t511.com")
    t2, _ = await _mkuser("a2@t511.com")
    t3, _ = await _mkuser("a3@t511.com")
    lid = await _seed_listing()

    for tok, rt in [(t1, 5), (t2, 4), (t3, 3)]:
        r = await client.post(
            f"/api/v1/model-marketplace/listings/{lid}/reviews",
            json={"rating": rt},
            headers=_h(tok),
        )
        assert r.status_code == 201

    # Aggregate endpoint
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/reviews/aggregate",
        headers=_h(t1),
    )
    body = r.json()
    assert body["review_count"] == 3
    assert body["average_rating"] == 4.0
    hist = {int(k): v for k, v in body["rating_histogram"].items()}
    assert hist == {1: 0, 2: 0, 3: 1, 4: 1, 5: 1}

    # ListingOut inline stats
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}",
        headers=_h(t1),
    )
    assert r.json()["review_count"] == 3
    assert r.json()["average_rating"] == 4.0


@pytest.mark.asyncio
async def test_delete_my_review_idempotent(client):
    tok, _ = await _mkuser("rv-del@t511.com")
    lid = await _seed_listing()

    r = await client.delete(
        f"/api/v1/model-marketplace/listings/{lid}/reviews/mine",
        headers=_h(tok),
    )
    assert r.status_code == 200

    await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        json={"rating": 4},
        headers=_h(tok),
    )
    r = await client.delete(
        f"/api/v1/model-marketplace/listings/{lid}/reviews/mine",
        headers=_h(tok),
    )
    assert r.status_code == 200
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/reviews",
        headers=_h(tok),
    )
    assert r.json() == []


@pytest.mark.asyncio
async def test_reject_bad_rating(client):
    tok, _ = await _mkuser("rv-bad@t511.com")
    lid = await _seed_listing()
    for bad in [0, 6, 999]:
        r = await client.post(
            f"/api/v1/model-marketplace/listings/{lid}/reviews",
            json={"rating": bad},
            headers=_h(tok),
        )
        assert r.status_code == 422
