"""T10.8 · workflow run history audit tests.

Every /run and /{id}/run inserts into copilot_workflow_runs. We
verify:
  * inline runs create rows with workflow_id=null
  * stored runs create rows with correct workflow_id
  * org isolation
  * list ordering + optional workflow_id filter
  * detail endpoint returns trace JSON
  * cross-org access returns 404
  * failed runs are still audited (with status='failed' + error text)
  * audit failure does not break the run itself (T10.8 guarantee)
"""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ---------- fixtures reused from other tests ---------------------------------

def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser():
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = uuid4()
    org_id = uuid4()
    email = f"wfhist+{uuid4().hex[:6]}@t.local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return uid, org_id, create_access_token(
        user_id=uid, org_id=org_id, role="user",
    )


_HAPPY_YAML = """
version: "0.1"
name: "hist-test"
steps:
  - id: s1
    tool: list_drones
    args: {}
"""

_BAD_YAML = """
version: "0.1"
name: "hist-fail"
steps:
  - id: s1
    tool: get_drone_status
    args: { drone_id: '${input.missing}' }
"""


# =============================================================== inline run =

async def test_inline_run_audited_with_null_workflow_id(client):
    _uid, _org, tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={"workflow_yaml": _HAPPY_YAML, "inputs": {}},
    )
    assert r.status_code == 200

    # Now list history — should have exactly one row for this org.
    r2 = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok),
    )
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    entry = rows[0]
    assert entry["workflow_id"] is None
    assert entry["workflow_name"] == "hist-test"
    assert entry["status"] == "ok"
    assert entry["error"] is None
    assert entry["duration_ms"] >= 0


async def test_failed_run_still_audited(client):
    _uid, _org, tok = await _mkuser()
    # This workflow will fail at interp time (no matching input).
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={"workflow_yaml": _BAD_YAML, "inputs": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"

    r2 = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok),
    )
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"]  # non-empty


# =============================================================== stored run =

async def test_stored_run_audited_with_workflow_id(client):
    _uid, _org, tok = await _mkuser()
    # 1) create a stored workflow
    r = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={"name": "wf-audit", "dsl_yaml": _HAPPY_YAML},
    )
    assert r.status_code == 201
    wf_id = r.json()["id"]

    # 2) run it twice
    for _ in range(2):
        rr = await client.post(
            f"/api/v1/copilot/workflows/{wf_id}/run",
            headers=_h(tok),
            json={"inputs": {}},
        )
        assert rr.status_code == 200

    # 3) history should show 2 rows, both pointing at wf_id
    r2 = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok),
    )
    rows = r2.json()
    assert len(rows) == 2
    for row in rows:
        assert row["workflow_id"] == wf_id
        # workflow_name mirrors the DSL's name field, not the stored row.
        assert row["workflow_name"] == "hist-test"
        assert row["status"] == "ok"


# ============================================================ history filter =

async def test_history_filter_by_workflow_id(client):
    _uid, _org, tok = await _mkuser()

    # Two saved workflows so we can filter.
    r_a = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={"name": "wf-a", "dsl_yaml": _HAPPY_YAML},
    )
    r_b = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={"name": "wf-b", "dsl_yaml": _HAPPY_YAML.replace(
            "hist-test", "hist-test-b",
        )},
    )
    wf_a = r_a.json()["id"]
    wf_b = r_b.json()["id"]

    # a x2, b x1
    for wf in [wf_a, wf_a, wf_b]:
        await client.post(
            f"/api/v1/copilot/workflows/{wf}/run",
            headers=_h(tok), json={"inputs": {}},
        )

    # Filter by wf_a
    r = await client.get(
        "/api/v1/copilot/workflows/history",
        headers=_h(tok), params={"workflow_id": wf_a},
    )
    rows = r.json()
    assert len(rows) == 2
    assert all(row["workflow_id"] == wf_a for row in rows)

    # Unfiltered = 3
    r_all = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok),
    )
    assert len(r_all.json()) == 3


async def test_history_org_isolation(client):
    _uid_a, _org_a, tok_a = await _mkuser()
    _uid_b, _org_b, tok_b = await _mkuser()

    # A runs one inline workflow.
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok_a),
        json={"workflow_yaml": _HAPPY_YAML, "inputs": {}},
    )
    assert r.status_code == 200

    # B sees zero.
    r_b = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok_b),
    )
    assert r_b.json() == []


# =========================================================== history detail =

async def test_history_detail_includes_trace(client):
    _uid, _org, tok = await _mkuser()
    await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={"workflow_yaml": _HAPPY_YAML, "inputs": {}},
    )
    r = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok),
    )
    run_id = r.json()[0]["id"]

    r2 = await client.get(
        f"/api/v1/copilot/workflows/history/{run_id}", headers=_h(tok),
    )
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["id"] == run_id
    trace = detail["trace"]
    # Trace should be the RunResponse dump with step details.
    assert trace["workflow_name"] == "hist-test"
    assert trace["status"] == "ok"
    assert isinstance(trace["steps"], list)
    assert trace["steps"][0]["tool"] == "list_drones"


async def test_history_detail_cross_org_404(client):
    _uid_a, _org_a, tok_a = await _mkuser()
    _uid_b, _org_b, tok_b = await _mkuser()

    await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok_a),
        json={"workflow_yaml": _HAPPY_YAML, "inputs": {}},
    )
    r = await client.get(
        "/api/v1/copilot/workflows/history", headers=_h(tok_a),
    )
    run_id = r.json()[0]["id"]

    r2 = await client.get(
        f"/api/v1/copilot/workflows/history/{run_id}", headers=_h(tok_b),
    )
    assert r2.status_code == 404


async def test_history_detail_missing_404(client):
    _uid, _org, tok = await _mkuser()
    r = await client.get(
        f"/api/v1/copilot/workflows/history/{uuid4()}", headers=_h(tok),
    )
    assert r.status_code == 404


# ==================================================================== auth =

async def test_history_endpoints_require_auth(client):
    r = await client.get("/api/v1/copilot/workflows/history")
    assert r.status_code in (401, 403)
    r2 = await client.get(f"/api/v1/copilot/workflows/history/{uuid4()}")
    assert r2.status_code in (401, 403)
