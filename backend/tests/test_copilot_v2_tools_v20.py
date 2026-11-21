"""T6.4 tests — Copilot v2 tools for Model Marketplace & Community.

Verifies the tools are registered in the default registry, honor tenant
isolation, and return the shape the Copilot agent expects.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest


async def _mk_org(name: str = "Org"):
    from app.db import engine
    from app.models.organization import Organization
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    oid = uuid4()
    async with S() as s:
        s.add(Organization(id=oid, name=f"{name}-{uuid4().hex[:4]}"))
        await s.commit()
    return oid


async def _mk_user(email: str, role: str = "user", *, org_id=None):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    async with S() as s:
        s.add(User(
            id=uid,
            email=email.replace("@", f"+{uuid4().hex[:6]}@"),
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
            org_id=org_id,
        ))
        await s.commit()
    return uid


def test_tools_registered():
    from app.services.tool_registry import build_default_registry
    r = build_default_registry()
    metas = {m["name"] for m in r.get_specs()}
    assert "list_installed_models" in metas
    assert "search_community" in metas


@pytest.mark.asyncio
async def test_search_community_tenant_scoped(client):
    from app.db import engine
    from app.models.community import CommunityPost
    from app.services.tool_registry import (
        ToolContext, build_default_registry,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    org_a = await _mk_org("A")
    org_b = await _mk_org("B")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add_all([
            CommunityPost(
                tenant_id=org_a, title="Alpha review",
                body="alpha org private post",
                moderation_status="approved",
            ),
            CommunityPost(
                tenant_id=org_b, title="Bravo review",
                body="bravo org private post",
                moderation_status="approved",
            ),
            CommunityPost(
                tenant_id=None, title="Public tips",
                body="everyone can see this",
                moderation_status="approved",
            ),
            CommunityPost(
                tenant_id=None, title="Draft only",
                body="pending should be filtered out",
                moderation_status="pending",
            ),
        ])
        await s.commit()

    r = build_default_registry()

    async with S() as s:
        # Org A user should see A's private post + the public one, not B's.
        ctx = ToolContext(
            user_id=uuid4(), org_id=org_a, db=s,
        )
        res = await r.call("search_community", {"query": "review"}, ctx)
        titles = {p["title"] for p in res["posts"]}
        assert "Alpha review" in titles
        assert "Bravo review" not in titles

        # Pending post is invisible even to admin via this tool
        # (search_community is a discovery helper, not a moderation queue).
        res = await r.call(
            "search_community", {"query": "pending"}, ctx,
        )
        assert res["count"] == 0


@pytest.mark.asyncio
async def test_list_installed_models_scoped(client):
    from app.db import engine
    from app.models.model_marketplace import (
        ModelDeployment, ModelListing, ModelVersion,
    )
    from app.services.tool_registry import (
        ToolContext, build_default_registry,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    org_a = await _mk_org("A")
    org_b = await _mk_org("B")
    owner = await _mk_user("mm_tool_own@x.com", org_id=org_a)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        listing = ModelListing(
            slug=f"tool-{uuid4().hex[:6]}",
            name="Tool detector",
            task="detection",
            framework="onnx",
            owner_user_id=owner,
            owner_org_id=org_a,
            visibility="public",
        )
        s.add(listing)
        await s.flush()
        ver = ModelVersion(
            listing_id=listing.id, version="1.0.0",
            artifact_uri="s3://x/y",
            artifact_sha256="a" * 64,
            review_status="approved",
        )
        s.add(ver)
        await s.flush()
        s.add(ModelDeployment(
            org_id=org_a, listing_id=listing.id, version_id=ver.id,
            status="installed", installed_by=owner,
            quota_calls_per_day=1000,
        ))
        await s.commit()

    r = build_default_registry()
    async with S() as s:
        # Org A sees its deployment.
        ctx = ToolContext(user_id=owner, org_id=org_a, db=s)
        res = await r.call("list_installed_models", {}, ctx)
        assert res["count"] == 1
        assert res["deployments"][0]["model_name"] == "Tool detector"
        assert res["deployments"][0]["quota_per_day"] == 1000

        # Org B sees nothing.
        ctx = ToolContext(user_id=uuid4(), org_id=org_b, db=s)
        res = await r.call("list_installed_models", {}, ctx)
        assert res["count"] == 0
