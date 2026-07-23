"""T7.11 — scene marketplace /facets."""
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
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid, org_id


async def _seed(org_id, category="power_grid", license="CC-BY-NC",
                tags=None, visibility="public"):
    from app.db import engine
    from app.models.scene_marketplace import SceneListing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    lid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(SceneListing(
            id=lid, org_id=org_id,
            scene_id=uuid4(),
            title=f"s-{uuid4().hex[:6]}",
            slug=f"sf-{uuid4().hex[:6]}",
            description="d",
            license=license, category=category,
            tags=tags or [], visibility=visibility,
        ))
        await s.commit()
    return lid


@pytest.mark.asyncio
async def test_scene_facets_categories_and_licenses(client):
    tok, _, org = await _mkuser("sf1@t711.com")
    await _seed(org, category="power_grid", license="CC-BY-NC")
    await _seed(org, category="power_grid", license="CC-BY-NC")
    await _seed(org, category="power_grid", license="Apache-2.0")
    await _seed(org, category="agriculture", license="CC-BY-NC")

    r = await client.get(
        "/api/v1/marketplace/scenes/facets", headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["categories"]["power_grid"] == 3
    assert body["categories"]["agriculture"] == 1
    assert body["licenses"]["CC-BY-NC"] == 3
    assert body["licenses"]["Apache-2.0"] == 1
    assert body["total"] == 4


@pytest.mark.asyncio
async def test_scene_facets_tag_expansion(client):
    tok, _, org = await _mkuser("sf2@t711.com")
    await _seed(org, tags=["urban", "night"])
    await _seed(org, tags=["urban", "day"])
    await _seed(org, tags=["night"])

    r = await client.get(
        "/api/v1/marketplace/scenes/facets", headers=_h(tok),
    )
    tags = r.json()["tags"]
    assert tags["urban"] == 2
    assert tags["night"] == 2
    assert tags["day"] == 1


@pytest.mark.asyncio
async def test_scene_facets_excludes_private(client):
    tok, _, org = await _mkuser("sf3@t711.com")
    await _seed(org, category="pub_cat", visibility="public")
    await _seed(org, category="priv_cat", visibility="org_only")

    r = await client.get(
        "/api/v1/marketplace/scenes/facets", headers=_h(tok),
    )
    cats = r.json()["categories"]
    assert cats.get("pub_cat") == 1
    assert "priv_cat" not in cats
