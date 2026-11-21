"""E2.6 · Workflow Marketplace 测试."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_workflow import CopilotWorkflow
from app.models.user import User
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(role: str = "user") -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"mkt+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid, org


async def _mkuser_in_org(org: UUID, role: str = "user") -> tuple[str, UUID]:
    uid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"peer+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid


_SAMPLE_YAML = """
version: "0.1"
name: "sample-wf"
description: "shared sample"
steps:
  - id: s1
    tool: list_drones
    args: {}
"""


async def _mkworkflow(owner: UUID, org: UUID, name: str = "wf-src") -> UUID:
    wid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotWorkflow(
            id=wid, org_id=org, owner_user_id=owner,
            name=name, description="src",
            dsl_yaml=_SAMPLE_YAML, version=1,
        ))
        await s.commit()
    return wid


# ============ Publish / Browse ============

async def test_publish_happy(client) -> None:
    tok, uid, org = await _mkuser()
    wid = await _mkworkflow(uid, org)
    r = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok),
        json={
            "workflow_id": str(wid), "title": "第一个共享 workflow",
            "summary": "无人机巡检模板", "tags": ["巡检", "示范"],
            "visibility": "public",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "第一个共享 workflow"
    assert body["install_count"] == 0
    assert body["rating_count"] == 0


async def test_publish_duplicate_same_version_rejected(client) -> None:
    tok, uid, org = await _mkuser()
    wid = await _mkworkflow(uid, org)
    r1 = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok),
        json={"workflow_id": str(wid), "title": "v1"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok),
        json={"workflow_id": str(wid), "title": "v1-dup"},
    )
    assert r2.status_code == 400
    assert "already published" in r2.text


async def test_publish_other_org_rejected(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    tok_b, _, _ = await _mkuser()
    wid = await _mkworkflow(uid_a, org_a)
    r = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_b),
        json={"workflow_id": str(wid), "title": "steal"},
    )
    assert r.status_code == 400
    assert "not authorized" in r.text


async def test_browse_public_visible_across_orgs(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={
            "workflow_id": str(wid_a), "title": "public-plane",
            "summary": "航线共享", "visibility": "public",
        },
    )
    tok_b, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflow-marketplace/listings", headers=_h(tok_b),
    )
    assert r.status_code == 200
    body = r.json()
    titles = [it["title"] for it in body["items"]]
    assert "public-plane" in titles


async def test_browse_org_visibility_isolates(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={
            "workflow_id": str(wid_a), "title": "internal-only",
            "visibility": "org",
        },
    )

    # Same org peer can see
    tok_peer, _ = await _mkuser_in_org(org_a)
    r_peer = await client.get(
        "/api/v1/copilot/workflow-marketplace/listings", headers=_h(tok_peer),
    )
    titles_peer = [it["title"] for it in r_peer.json()["items"]]
    assert "internal-only" in titles_peer

    # Other org cannot
    tok_b, _, _ = await _mkuser()
    r_b = await client.get(
        "/api/v1/copilot/workflow-marketplace/listings", headers=_h(tok_b),
    )
    titles_b = [it["title"] for it in r_b.json()["items"]]
    assert "internal-only" not in titles_b


async def test_browse_query_filter(client) -> None:
    tok, uid, org = await _mkuser()
    wid = await _mkworkflow(uid, org, name="agri-wf")
    await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok),
        json={
            "workflow_id": str(wid), "title": "农业植保自动巡田",
            "summary": "包含遥感 + 施肥两步", "tags": ["农业"],
        },
    )
    r = await client.get(
        "/api/v1/copilot/workflow-marketplace/listings?q=植保", headers=_h(tok),
    )
    body = r.json()
    assert any("植保" in it["title"] for it in body["items"])


# ============ Install ============

async def test_install_creates_new_workflow(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "shared-wf"},
    )
    listing_id = pub.json()["id"]

    tok_b, uid_b, org_b = await _mkuser()
    r = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/install",
        headers=_h(tok_b), json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow_name"] == "shared-wf"
    assert body["listing_install_count"] == 1

    # Check counter propagated
    detail = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}",
        headers=_h(tok_b),
    )
    assert detail.json()["install_count"] == 1


async def test_install_name_conflict_disambiguates(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "dup-name"},
    )
    listing_id = pub.json()["id"]

    tok_b, uid_b, org_b = await _mkuser()
    # Pre-create a workflow with the same name in target org
    await _mkworkflow(uid_b, org_b, name="dup-name")

    r = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/install",
        headers=_h(tok_b), json={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_name"] == "dup-name (2)"


async def test_install_org_private_rejected(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={
            "workflow_id": str(wid_a), "title": "private-x",
            "visibility": "org",
        },
    )
    listing_id = pub.json()["id"]

    tok_b, _, _ = await _mkuser()  # Different org
    r = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/install",
        headers=_h(tok_b), json={},
    )
    assert r.status_code == 400


# ============ Ratings ============

async def test_rate_and_avg_updates(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "rateable"},
    )
    listing_id = pub.json()["id"]

    tok_b, _, _ = await _mkuser()
    r1 = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_b), json={"stars": 4, "comment": "不错"},
    )
    assert r1.status_code == 200

    tok_c, _, _ = await _mkuser()
    await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_c), json={"stars": 5},
    )

    detail = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}",
        headers=_h(tok_a),
    )
    body = detail.json()
    assert body["rating_count"] == 2
    assert body["avg_rating"] == 4.5


async def test_rate_upsert_same_rater(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "rate-me"},
    )
    listing_id = pub.json()["id"]

    tok_b, _, _ = await _mkuser()
    await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_b), json={"stars": 3},
    )
    await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_b), json={"stars": 5, "comment": "改口称赞"},
    )
    detail = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}",
        headers=_h(tok_a),
    )
    body = detail.json()
    assert body["rating_count"] == 1
    assert body["avg_rating"] == 5.0


async def test_rate_self_rejected(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "own"},
    )
    listing_id = pub.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_a), json={"stars": 5},
    )
    assert r.status_code == 400


async def test_my_rating_endpoint(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "mine-check"},
    )
    listing_id = pub.json()["id"]

    tok_b, _, _ = await _mkuser()
    my0 = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/my-rating",
        headers=_h(tok_b),
    )
    assert my0.json() is None

    await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/rate",
        headers=_h(tok_b), json={"stars": 4},
    )
    my1 = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/my-rating",
        headers=_h(tok_b),
    )
    assert my1.json()["stars"] == 4


# ============ Unpublish & Installs analytics ============

async def test_unpublish_hides_from_browse(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "goes-away"},
    )
    listing_id = pub.json()["id"]

    r_del = await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/unpublish",
        headers=_h(tok_a),
    )
    assert r_del.status_code == 204

    tok_b, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflow-marketplace/listings", headers=_h(tok_b),
    )
    titles = [it["title"] for it in r.json()["items"]]
    assert "goes-away" not in titles


async def test_installs_analytics_author_only(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    wid_a = await _mkworkflow(uid_a, org_a)
    pub = await client.post(
        "/api/v1/copilot/workflow-marketplace/publish", headers=_h(tok_a),
        json={"workflow_id": str(wid_a), "title": "analytics-test"},
    )
    listing_id = pub.json()["id"]

    tok_b, _, _ = await _mkuser()
    await client.post(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/install",
        headers=_h(tok_b), json={},
    )

    # Author can view
    r_auth = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/installs",
        headers=_h(tok_a),
    )
    assert r_auth.status_code == 200
    assert len(r_auth.json()["items"]) == 1

    # Non-author cannot
    r_denied = await client.get(
        f"/api/v1/copilot/workflow-marketplace/listings/{listing_id}/installs",
        headers=_h(tok_b),
    )
    assert r_denied.status_code == 403
