"""Admin CRUD API tests — v1.0 users & orgs.

These are integration tests that hit the actual Users/Organizations
tables. On CI/dev without Postgres they're skipped because the ORM
uses Postgres-specific server defaults (gen_random_uuid, etc.) that
SQLite can't emulate cleanly.
"""
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    "postgresql" not in os.environ.get("DATABASE_URL", ""),
    reason="admin CRUD requires Postgres (uses gen_random_uuid server default)",
)


@pytest.mark.asyncio
async def test_admin_org_lifecycle(client):
    r = await client.post(
        "/api/v1/admin/organizations", json={"name": "test-org-alpha"}
    )
    assert r.status_code == 201, r.text
    org_id = r.json()["id"]

    # Duplicate rejected
    r = await client.post(
        "/api/v1/admin/organizations", json={"name": "test-org-alpha"}
    )
    assert r.status_code == 409

    r = await client.get("/api/v1/admin/organizations")
    assert r.status_code == 200
    names = {o["name"] for o in r.json()}
    assert "test-org-alpha" in names

    # Create a user under this org
    r = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "alpha.op@e2e.local",
            "password": "hunter2!",
            "role": "operator",
            "org_id": org_id,
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["role"] == "operator"
    assert user["org_id"] == org_id
    assert user["is_active"] is True


@pytest.mark.asyncio
async def test_admin_user_role_change(client):
    # Create user
    r = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "promoteme@e2e.local",
            "password": "hunter2!",
            "role": "viewer",
        },
    )
    assert r.status_code == 201
    uid = r.json()["id"]

    # Promote to admin
    r = await client.patch(
        f"/api/v1/admin/users/{uid}", json={"role": "admin"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"

    # Invalid role rejected
    r = await client.patch(
        f"/api/v1/admin/users/{uid}", json={"role": "god-mode"}
    )
    assert r.status_code == 400

    # Deactivate
    r = await client.delete(f"/api/v1/admin/users/{uid}")
    assert r.status_code == 200
    assert r.json()["deactivated"] == uid


@pytest.mark.asyncio
async def test_admin_user_list_filter_by_org(client):
    # Create org
    r = await client.post(
        "/api/v1/admin/organizations", json={"name": "filter-org"}
    )
    org_id = r.json()["id"]

    # 3 users under this org
    for i in range(3):
        r = await client.post(
            "/api/v1/admin/users",
            json={
                "email": f"filter-user-{i}@e2e.local",
                "password": "hunter2!",
                "role": "operator",
                "org_id": org_id,
            },
        )
        assert r.status_code == 201

    r = await client.get(f"/api/v1/admin/users?org_id={org_id}")
    assert r.status_code == 200
    users = r.json()
    assert len(users) >= 3
    for u in users:
        assert u["org_id"] == org_id
