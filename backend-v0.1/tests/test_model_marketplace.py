"""Model Marketplace API tests — T6.2 (v2.0 §3.16 MVP)."""
from __future__ import annotations

from uuid import uuid4

import pytest


async def _make_user(client, email: str, role: str = "user", *, org_id=None) -> tuple[str, str]:
    """Return (token, user_id_str). Mints JWT directly to bypass login RL."""
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    user_id = uuid4()
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=user_id, email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
            org_id=org_id,
        ))
        await s.commit()
    tok = create_access_token(user_id=user_id, org_id=org_id, role=role)
    return tok, str(user_id)


async def _make_org(name: str = "Org A"):
    from app.db import engine
    from app.models.organization import Organization
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    oid = uuid4()
    async with Session() as s:
        s.add(Organization(id=oid, name=f"{name}-{uuid4().hex[:4]}"))
        await s.commit()
    return oid


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# Listing lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_listing_and_list_public(client):
    org = await _make_org("A")
    tok, _ = await _make_user(client, "mm_a@x.com", org_id=org)

    slug = f"yolo-drone-{uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/model-marketplace/listings",
        json={
            "slug": slug,
            "name": "YOLOv8 Drone Detection",
            "description": "detect drones from ground station cameras",
            "task": "detection",
            "framework": "onnx",
            "tags": ["drone", "detection"],
            "visibility": "public",
            "license": "apache-2",
            "price_model": "per_call",
            "price_unit": "0.001",
        },
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == slug
    assert body["visibility"] == "public"

    r = await client.get(
        "/api/v1/model-marketplace/listings?task=detection",
        headers=_h(tok),
    )
    assert r.status_code == 200
    slugs = [l["slug"] for l in r.json()["items"]]
    assert slug in slugs


@pytest.mark.asyncio
async def test_slug_conflict_returns_409(client):
    tok, _ = await _make_user(client, "mm_dup@x.com")
    slug = f"dupe-{uuid4().hex[:6]}"
    payload = {
        "slug": slug, "name": "x", "task": "detection", "framework": "onnx",
    }
    r = await client.post(
        "/api/v1/model-marketplace/listings", json=payload, headers=_h(tok),
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/v1/model-marketplace/listings", json=payload, headers=_h(tok),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_private_listing_hidden_from_others(client):
    org_a = await _make_org("A")
    org_b = await _make_org("B")
    a_tok, _ = await _make_user(client, "mm_priv_a@x.com", org_id=org_a)
    b_tok, _ = await _make_user(client, "mm_priv_b@x.com", org_id=org_b)

    r = await client.post(
        "/api/v1/model-marketplace/listings",
        json={
            "slug": f"priv-{uuid4().hex[:6]}",
            "name": "私有模型",
            "task": "detection", "framework": "pytorch",
            "visibility": "private",
        },
        headers=_h(a_tok),
    )
    lid = r.json()["id"]
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}", headers=_h(b_tok),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Version review flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_review_lifecycle(client):
    org = await _make_org("A")
    tok, _ = await _make_user(client, "mm_v_owner@x.com", org_id=org)
    admin_tok, _ = await _make_user(client, "mm_v_admin@x.com", role="admin")
    other_tok, _ = await _make_user(client, "mm_v_other@x.com", org_id=await _make_org("C"))

    slug = f"v-{uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/model-marketplace/listings",
        json={"slug": slug, "name": "v", "task": "detection", "framework": "onnx"},
        headers=_h(tok),
    )
    lid = r.json()["id"]

    # Non-owner cannot push a version.
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        json={
            "version": "1.0.0",
            "artifact_uri": "s3://bucket/x.onnx",
            "artifact_sha256": "a" * 64,
        },
        headers=_h(other_tok),
    )
    assert r.status_code == 403

    # Owner pushes v1.0.0 (pending).
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        json={
            "version": "1.0.0",
            "artifact_uri": "s3://bucket/x.onnx",
            "artifact_sha256": "a" * 64,
            "size_bytes": 12_345_678,
            "hardware": ["cuda>=11.8", "vram>=8gb"],
            "benchmark": {"mAP@0.5": 0.72},
        },
        headers=_h(tok),
    )
    assert r.status_code == 201
    ver = r.json()
    assert ver["review_status"] == "pending"
    vid = ver["id"]

    # Duplicate version → 409.
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        json={
            "version": "1.0.0",
            "artifact_uri": "s3://bucket/x.onnx",
            "artifact_sha256": "a" * 64,
        },
        headers=_h(tok),
    )
    assert r.status_code == 409

    # Non-owner list → sees zero (pending hidden).
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        headers=_h(other_tok),
    )
    assert r.status_code == 200
    assert len(r.json()) == 0

    # Non-admin cannot review.
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/review",
        json={"action": "approve"},
        headers=_h(tok),
    )
    assert r.status_code == 403

    # Admin approves.
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/review",
        json={"action": "approve", "note": "LGTM"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "approved"

    # Non-owner list now sees the approved version.
    r = await client.get(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        headers=_h(other_tok),
    )
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Install + usage + quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_requires_approved_or_ownership(client):
    org_a = await _make_org("A")
    org_b = await _make_org("B")
    owner_tok, _ = await _make_user(client, "mm_i_own@x.com", org_id=org_a)
    other_tok, _ = await _make_user(client, "mm_i_other@x.com", org_id=org_b)
    admin_tok, _ = await _make_user(client, "mm_i_adm@x.com", role="admin")

    r = await client.post(
        "/api/v1/model-marketplace/listings",
        json={
            "slug": f"i-{uuid4().hex[:6]}",
            "name": "install-test",
            "task": "detection",
            "framework": "onnx",
        },
        headers=_h(owner_tok),
    )
    lid = r.json()["id"]
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        json={
            "version": "0.1.0",
            "artifact_uri": "s3://x",
            "artifact_sha256": "b" * 64,
        },
        headers=_h(owner_tok),
    )
    vid = r.json()["id"]

    # Other org cannot install a pending version.
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/install",
        json={"quota_calls_per_day": 100},
        headers=_h(other_tok),
    )
    assert r.status_code == 403

    # Owner can install unapproved (internal test).
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/install",
        headers=_h(owner_tok),
    )
    assert r.status_code == 201
    dep1 = r.json()

    # Idempotency: second install returns same deployment.
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/install",
        headers=_h(owner_tok),
    )
    assert r.status_code == 201
    assert r.json()["id"] == dep1["id"]

    # Admin approves → other org can install now.
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/review",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/install",
        json={"quota_calls_per_day": 5},
        headers=_h(other_tok),
    )
    assert r.status_code == 201
    dep2 = r.json()

    # Record usage — 3 calls OK.
    for _ in range(3):
        r = await client.post(
            f"/api/v1/model-marketplace/deployments/{dep2['id']}/usage",
            json={"units": 1, "unit_type": "call"},
            headers=_h(other_tok),
        )
        assert r.status_code == 201
    # Quota=5, already 3, +3 would overflow → 429.
    r = await client.post(
        f"/api/v1/model-marketplace/deployments/{dep2['id']}/usage",
        json={"units": 3, "unit_type": "call"},
        headers=_h(other_tok),
    )
    assert r.status_code == 429

    # Cross-org usage recording forbidden.
    r = await client.post(
        f"/api/v1/model-marketplace/deployments/{dep2['id']}/usage",
        json={"units": 1, "unit_type": "call"},
        headers=_h(owner_tok),  # owner is in org_a, dep2 lives in org_b
    )
    assert r.status_code == 403

    # Usage summary reflects the 3 recorded ok calls.
    r = await client.get(
        f"/api/v1/model-marketplace/deployments/{dep2['id']}/usage-summary",
        headers=_h(other_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_units"] == 3
    assert body["by_outcome"].get("ok") == 3


@pytest.mark.asyncio
async def test_list_deployments_scoped_to_org(client):
    org_a = await _make_org("A")
    org_b = await _make_org("B")
    a_tok, _ = await _make_user(client, "mm_dep_a@x.com", org_id=org_a)
    b_tok, _ = await _make_user(client, "mm_dep_b@x.com", org_id=org_b)
    admin_tok, _ = await _make_user(client, "mm_dep_adm@x.com", role="admin")

    # A publishes an approved version, B installs.
    r = await client.post(
        "/api/v1/model-marketplace/listings",
        json={
            "slug": f"d-{uuid4().hex[:6]}",
            "name": "d",
            "task": "detection",
            "framework": "onnx",
        },
        headers=_h(a_tok),
    )
    lid = r.json()["id"]
    r = await client.post(
        f"/api/v1/model-marketplace/listings/{lid}/versions",
        json={"version": "0.1.0", "artifact_uri": "s3://d",
              "artifact_sha256": "c" * 64},
        headers=_h(a_tok),
    )
    vid = r.json()["id"]
    await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/review",
        json={"action": "approve"},
        headers=_h(admin_tok),
    )
    await client.post(
        f"/api/v1/model-marketplace/versions/{vid}/install",
        headers=_h(b_tok),
    )

    # A sees zero deployments, B sees one.
    r = await client.get(
        "/api/v1/model-marketplace/deployments", headers=_h(a_tok),
    )
    assert r.status_code == 200
    assert all(d["org_id"] != str(org_b) for d in r.json())
    r = await client.get(
        "/api/v1/model-marketplace/deployments", headers=_h(b_tok),
    )
    assert len(r.json()) >= 1
