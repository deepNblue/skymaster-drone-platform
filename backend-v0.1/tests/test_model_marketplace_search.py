"""T5.12 — marketplace search + sort presets."""
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


async def _seed_listing(name, description=None):
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    lid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=lid,
            slug=f"s-{uuid4().hex[:6]}",
            name=name,
            description=description,
            task="detection",
            framework="pytorch",
            visibility="public",
        ))
        await s.commit()
    return lid


async def _seed_review(lid, rating):
    from app.db import engine
    from app.models.model_marketplace import ModelListingReview
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    async with S() as s:
        s.add(User(
            id=uid, email=f"r{uuid4().hex[:6]}@t512.com",
            hashed_pw=hash_password("x"), role="user", org_id=uuid4(),
        ))
        await s.commit()
    async with S() as s:
        s.add(ModelListingReview(
            listing_id=lid, user_id=uid, rating=rating,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_free_text_search_matches_name_and_description(client):
    tok, _ = await _mkuser("sr1@t512.com")
    a = await _seed_listing("YOLO Fast Detector")
    b = await _seed_listing("PPQuality Inspector", "yolo family reimplementation")
    c = await _seed_listing("Cat Segmenter")

    r = await client.get(
        "/api/v1/model-marketplace/listings",
        params={"q": "yolo"},
        headers=_h(tok),
    )
    ids = {x["id"] for x in r.json()["items"]}
    assert str(a) in ids  # matched name
    assert str(b) in ids  # matched description
    assert str(c) not in ids


@pytest.mark.asyncio
async def test_search_is_case_insensitive(client):
    tok, _ = await _mkuser("sr2@t512.com")
    a = await _seed_listing("YoLo Ultra")
    r = await client.get(
        "/api/v1/model-marketplace/listings",
        params={"q": "yolo"},
        headers=_h(tok),
    )
    ids = {x["id"] for x in r.json()["items"]}
    assert str(a) in ids


@pytest.mark.asyncio
async def test_sort_top_rated_prefers_reviewed_over_untouched(client):
    tok, _ = await _mkuser("sr3@t512.com")
    reviewed = await _seed_listing("Reviewed Model")
    unreviewed = await _seed_listing("Unreviewed Model")
    for rt in [5, 5, 4]:  # 3 reviews avg 4.67
        await _seed_review(reviewed, rt)

    r = await client.get(
        "/api/v1/model-marketplace/listings",
        params={"sort": "top_rated"},
        headers=_h(tok),
    )
    items = r.json()["items"]
    subset = [x["id"] for x in items if x["id"] in {str(reviewed), str(unreviewed)}]
    # Reviewed (≥3 reviews) must come first
    assert subset[0] == str(reviewed)


@pytest.mark.asyncio
async def test_sort_newest_orders_by_created_at_desc(client):
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from datetime import datetime, timezone, timedelta

    tok, _ = await _mkuser("sr4@t512.com")
    S = async_sessionmaker(engine, expire_on_commit=False)
    a_id = uuid4()
    b_id = uuid4()
    now = datetime.now(timezone.utc)
    async with S() as s:
        s.add(ModelListing(
            id=a_id, slug=f"o-{uuid4().hex[:6]}", name="Older",
            task="detection", framework="pytorch", visibility="public",
            created_at=now - timedelta(hours=2),
        ))
        s.add(ModelListing(
            id=b_id, slug=f"n-{uuid4().hex[:6]}", name="Newer",
            task="detection", framework="pytorch", visibility="public",
            created_at=now,
        ))
        await s.commit()

    r = await client.get(
        "/api/v1/model-marketplace/listings",
        params={"sort": "newest"},
        headers=_h(tok),
    )
    ids = [x["id"] for x in r.json()["items"] if x["id"] in {str(a_id), str(b_id)}]
    assert ids == [str(b_id), str(a_id)]
