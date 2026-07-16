"""T10.5 persistence tests for /copilot/workflows CRUD + stored /run."""
from __future__ import annotations

from uuid import UUID


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(org_id=None):
    from uuid import uuid4 as _u
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = _u()
    org_id = org_id or _u()
    email = f"wfp+{_u().hex[:6]}@t.local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user"), org_id


def _uniq(prefix: str) -> str:
    """Random name suffix so tests never collide on the (org_id, name)
    partial unique index — sqlite :memory: shares one pool across tests."""
    from uuid import uuid4
    return f"{prefix}-{uuid4().hex[:8]}"


_VALID_DSL = """
version: "0.1"
name: "smoke"
description: "trivial happy-path workflow"
steps:
  - id: s1
    tool: list_drones
    args: {}
"""


# ================================================================== create =


async def test_create_workflow_happy(client):
    tok, _org = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={
            "name": "wf-1",
            "description": "hello",
            "dsl_yaml": _VALID_DSL,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "wf-1"
    assert body["version"] == 1
    assert body["dsl_yaml"] == _VALID_DSL
    UUID(body["id"])
    assert body["created_at"]
    assert body["updated_at"]


async def test_create_workflow_invalid_dsl_rejected(client):
    tok, _org = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={
            "name": "wf-bad",
            "dsl_yaml": ":: not valid yaml [",
        },
    )
    assert r.status_code == 400
    assert "syntax" in r.text.lower() or "parse" in r.text.lower()


async def test_create_workflow_unknown_tool_rejected(client):
    tok, _org = await _mkuser()
    dsl = """
version: "0.1"
name: "bad"
steps:
  - id: s
    tool: ghost_tool
    args: {}
"""
    r = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={"name": "wf-bad", "dsl_yaml": dsl},
    )
    assert r.status_code == 400
    assert "ghost_tool" in r.text


async def test_create_workflow_duplicate_name_conflict(client):
    tok, _org = await _mkuser()
    payload = {"name": "same", "dsl_yaml": _VALID_DSL}
    r1 = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok), json=payload
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok), json=payload
    )
    assert r2.status_code == 409
    assert "already exists" in r2.text


# ==================================================================== list =


async def test_list_workflows_scoped_to_org(client):
    """Two different orgs — each sees only its own workflows."""
    tokA, _ = await _mkuser()
    tokB, _ = await _mkuser()

    await client.post(
        "/api/v1/copilot/workflows", headers=_h(tokA),
        json={"name": "a-wf", "dsl_yaml": _VALID_DSL},
    )
    await client.post(
        "/api/v1/copilot/workflows", headers=_h(tokB),
        json={"name": "b-wf", "dsl_yaml": _VALID_DSL},
    )

    lA = await client.get("/api/v1/copilot/workflows", headers=_h(tokA))
    lB = await client.get("/api/v1/copilot/workflows", headers=_h(tokB))
    assert lA.status_code == 200 and lB.status_code == 200
    a_names = {w["name"] for w in lA.json()}
    b_names = {w["name"] for w in lB.json()}
    assert "a-wf" in a_names and "b-wf" not in a_names
    assert "b-wf" in b_names and "a-wf" not in b_names


# ==================================================================== get =


async def test_get_workflow_returns_dsl(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "wf-get", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.get(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tok)
    )
    assert r.status_code == 200
    assert r.json()["dsl_yaml"] == _VALID_DSL


async def test_get_cross_org_returns_404(client):
    tokA, _ = await _mkuser()
    tokB, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tokA),
        json={"name": "wf-a", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.get(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tokB)
    )
    # Never leak existence across tenants.
    assert r.status_code == 404


# ================================================================== update =


async def test_update_workflow_optimistic_lock_ok(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "u", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.put(
        f"/api/v1/copilot/workflows/{wf_id}",
        headers=_h(tok),
        json={"description": "updated", "version": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "updated"
    assert body["version"] == 2


async def test_update_workflow_stale_version_conflict(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "u2", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    # Bump version once.
    r1 = await client.put(
        f"/api/v1/copilot/workflows/{wf_id}",
        headers=_h(tok),
        json={"description": "v2", "version": 1},
    )
    assert r1.status_code == 200
    # Second caller still holds version=1 → 409.
    r2 = await client.put(
        f"/api/v1/copilot/workflows/{wf_id}",
        headers=_h(tok),
        json={"description": "stale", "version": 1},
    )
    assert r2.status_code == 409
    assert "stale" in r2.text.lower()


async def test_update_workflow_bad_dsl_rejected(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "u3", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.put(
        f"/api/v1/copilot/workflows/{wf_id}",
        headers=_h(tok),
        json={"dsl_yaml": ":: broken yaml [", "version": 1},
    )
    assert r.status_code == 400


async def test_update_cross_org_returns_404(client):
    tokA, _ = await _mkuser()
    tokB, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tokA),
        json={"name": "a", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.put(
        f"/api/v1/copilot/workflows/{wf_id}",
        headers=_h(tokB),
        json={"description": "x", "version": 1},
    )
    assert r.status_code == 404


# ================================================================== delete =


async def test_delete_workflow_soft_and_hidden_from_list(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "del", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]

    r = await client.delete(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tok)
    )
    assert r.status_code == 204

    # 404 from now on
    g = await client.get(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tok)
    )
    assert g.status_code == 404

    # Not in list
    l = await client.get("/api/v1/copilot/workflows", headers=_h(tok))
    assert all(w["id"] != wf_id for w in l.json())


async def test_delete_then_reuse_name_allowed(client):
    """Partial unique index (deleted_at IS NULL) lets a deleted name be
    reclaimed."""
    tok, _ = await _mkuser()
    c1 = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "reuse", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c1.json()["id"]
    d = await client.delete(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tok)
    )
    assert d.status_code == 204
    c2 = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "reuse", "dsl_yaml": _VALID_DSL},
    )
    assert c2.status_code == 201, c2.text


# ============================================================== stored run =


async def test_stored_run_happy(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "sr", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/workflows/{wf_id}/run",
        headers=_h(tok),
        json={"inputs": {}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["workflow_name"] == "smoke"
    assert body["steps"][0]["status"] == "ok"


async def test_stored_run_cross_org_404(client):
    tokA, _ = await _mkuser()
    tokB, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tokA),
        json={"name": "cross", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/workflows/{wf_id}/run",
        headers=_h(tokB),
        json={"inputs": {}},
    )
    assert r.status_code == 404


async def test_stored_run_after_delete_404(client):
    tok, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/workflows", headers=_h(tok),
        json={"name": "gone", "dsl_yaml": _VALID_DSL},
    )
    wf_id = c.json()["id"]
    await client.delete(
        f"/api/v1/copilot/workflows/{wf_id}", headers=_h(tok)
    )
    r = await client.post(
        f"/api/v1/copilot/workflows/{wf_id}/run",
        headers=_h(tok), json={"inputs": {}},
    )
    assert r.status_code == 404


# =================================================================== auth =


async def test_persist_endpoints_require_auth(client):
    """All persistence endpoints must reject anonymous."""
    from uuid import uuid4
    fake = str(uuid4())
    responses = [
        await client.post(
            "/api/v1/copilot/workflows",
            json={"name": "x", "dsl_yaml": _VALID_DSL},
        ),
        await client.get("/api/v1/copilot/workflows"),
        await client.get(f"/api/v1/copilot/workflows/{fake}"),
        await client.put(
            f"/api/v1/copilot/workflows/{fake}",
            json={"description": "x", "version": 1},
        ),
        await client.delete(f"/api/v1/copilot/workflows/{fake}"),
        await client.post(
            f"/api/v1/copilot/workflows/{fake}/run",
            json={"inputs": {}},
        ),
    ]
    for r in responses:
        assert r.status_code in (401, 403), r.status_code
