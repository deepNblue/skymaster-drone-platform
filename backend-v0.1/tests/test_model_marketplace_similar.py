"""T5.14 — GET /listings/{id}/similar."""
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


async def _seed(task="detection", framework="pytorch", tags=None,
                visibility="public"):
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    lid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=lid,
            slug=f"sm-{uuid4().hex[:6]}",
            name=f"m-{uuid4().hex[:6]}",
            task=task, framework=framework,
            tags=tags or [],
            visibility=visibility,
        ))
        await s.commit()
    return lid


@pytest.mark.asyncio
async def test_similar_prefers_same_task_same_framework_shared_tags(client):
    tok, _ = await _mkuser("s1@t514.com")
    seed = await _seed(task="detection", framework="pytorch",
                       tags=["yolo", "fast"])
    twin = await _seed(task="detection", framework="pytorch",
                       tags=["yolo", "fast"])  # score 3+2+2=7
    same_task_only = await _seed(task="detection", framework="tensorflow",
                                 tags=[])   # 3
    unrelated = await _seed(task="segmentation", framework="jax",
                            tags=["nerf"])  # 0

    r = await client.get(
        f"/api/v1/model-marketplace/listings/{seed}/similar",
        headers=_h(tok),
    )
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert ids[0] == str(twin)
    assert str(same_task_only) in ids
    assert str(unrelated) not in ids


@pytest.mark.asyncio
async def test_similar_excludes_the_seed_itself(client):
    tok, _ = await _mkuser("s2@t514.com")
    seed = await _seed(task="detection", framework="pytorch")
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{seed}/similar",
        headers=_h(tok),
    )
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert str(seed) not in ids


@pytest.mark.asyncio
async def test_similar_404_on_missing_listing(client):
    tok, _ = await _mkuser("s3@t514.com")
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{uuid4()}/similar",
        headers=_h(tok),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_similar_excludes_private_listings(client):
    tok, _ = await _mkuser("s4@t514.com")
    seed = await _seed(task="detection", framework="pytorch")
    priv = await _seed(task="detection", framework="pytorch",
                       visibility="private")
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{seed}/similar",
        headers=_h(tok),
    )
    ids = [x["id"] for x in r.json()]
    assert str(priv) not in ids
