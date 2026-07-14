"""T5.9 — deployment_count + version_count aggregate on ListingOut."""
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


async def _seed_listing_with_deps(n_versions=2, n_active=3, n_uninstalled=1):
    """Seed a public listing with a few versions and deployments."""
    from app.db import engine
    from app.models.model_marketplace import (
        ModelListing, ModelVersion, ModelDeployment,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    listing_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(ModelListing(
            id=listing_id,
            slug=f"yolo-drone-{uuid4().hex[:6]}",
            name="YOLO Drone",
            task="detection",
            framework="pytorch",
            visibility="public",
        ))
        # Need an org row because ModelDeployment.org_id FKs it
        from app.models.organization import Organization
        org_id = uuid4()
        s.add(Organization(id=org_id, name=f"test-org-{uuid4().hex[:6]}"))
        version_ids = []
        for i in range(n_versions):
            vid = uuid4()
            version_ids.append(vid)
            s.add(ModelVersion(
                id=vid,
                listing_id=listing_id,
                version=f"1.0.{i}",
                artifact_uri=f"s3://bucket/yolo-{i}.pt",
                artifact_sha256="0" * 64,
            ))
        # Active/installed deployments on version[0]
        for _ in range(n_active):
            s.add(ModelDeployment(
                id=uuid4(),
                version_id=version_ids[0],
                listing_id=listing_id,
                org_id=org_id,
                status="active",
            ))
        # A dangling 'uninstalled' deployment (should NOT be counted)
        for _ in range(n_uninstalled):
            s.add(ModelDeployment(
                id=uuid4(),
                version_id=version_ids[0],
                listing_id=listing_id,
                org_id=org_id,
                status="uninstalled",
            ))
        await s.commit()
    return listing_id


@pytest.mark.asyncio
async def test_listing_out_carries_aggregate_counts(client):
    tok, _, _ = await _mkuser("aggr@t59.com")
    lid = await _seed_listing_with_deps(
        n_versions=2, n_active=3, n_uninstalled=1,
    )

    # Listing detail
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deployment_count"] == 3, body
    assert body["version_count"] == 2, body

    # Listing list
    r = await client.get(
        "/api/v1/model-marketplace/listings", headers=_h(tok),
    )
    assert r.status_code == 200
    found = next(
        (x for x in r.json()["items"] if x["id"] == str(lid)), None,
    )
    assert found is not None
    assert found["deployment_count"] == 3
    assert found["version_count"] == 2


@pytest.mark.asyncio
async def test_zero_deployments_returns_zero_not_null(client):
    tok, _, _ = await _mkuser("zero@t59.com")
    lid = await _seed_listing_with_deps(
        n_versions=1, n_active=0, n_uninstalled=0,
    )
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(tok),
    )
    body = r.json()
    assert body["deployment_count"] == 0
    assert body["version_count"] == 1
