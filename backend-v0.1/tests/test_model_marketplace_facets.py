"""T5.13 — GET /model-marketplace/facets."""
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


async def _seed_listing(task="detection", framework="pytorch",
                        tags=None, visibility="public"):
    from app.db import engine
    from app.models.model_marketplace import ModelListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    lid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=lid,
            slug=f"f-{uuid4().hex[:6]}",
            name=f"m-{uuid4().hex[:6]}",
            task=task,
            framework=framework,
            tags=tags or [],
            visibility=visibility,
        ))
        await s.commit()
    return lid


@pytest.mark.asyncio
async def test_facets_task_and_framework_counts(client):
    tok, _ = await _mkuser("f1@t513.com")
    # 2 detection/pytorch + 1 detection/tf + 1 segmentation/pytorch
    await _seed_listing(task="detection", framework="pytorch")
    await _seed_listing(task="detection", framework="pytorch")
    await _seed_listing(task="detection", framework="tensorflow")
    await _seed_listing(task="segmentation", framework="pytorch")

    r = await client.get(
        "/api/v1/model-marketplace/facets", headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tasks"]["detection"] == 3
    assert body["tasks"]["segmentation"] == 1
    assert body["frameworks"]["pytorch"] == 3
    assert body["frameworks"]["tensorflow"] == 1
    assert body["total"] == 4


@pytest.mark.asyncio
async def test_facets_tag_expansion(client):
    tok, _ = await _mkuser("f2@t513.com")
    await _seed_listing(tags=["fast", "yolo"])
    await _seed_listing(tags=["fast", "onnx"])
    await _seed_listing(tags=["yolo"])
    await _seed_listing(tags=[])

    r = await client.get(
        "/api/v1/model-marketplace/facets", headers=_h(tok),
    )
    tags = r.json()["tags"]
    assert tags["fast"] == 2
    assert tags["yolo"] == 2
    assert tags["onnx"] == 1


@pytest.mark.asyncio
async def test_facets_excludes_private_listings(client):
    tok, _ = await _mkuser("f3@t513.com")
    await _seed_listing(task="private_only", visibility="private")
    await _seed_listing(task="public_only", visibility="public")

    r = await client.get(
        "/api/v1/model-marketplace/facets", headers=_h(tok),
    )
    tasks = r.json()["tasks"]
    assert tasks.get("public_only") == 1
    assert "private_only" not in tasks
