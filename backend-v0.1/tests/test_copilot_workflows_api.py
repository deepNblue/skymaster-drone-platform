"""REST integration tests for /copilot/workflows endpoints (T10.3)."""
from __future__ import annotations

from uuid import uuid4

import pytest


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser():
    from uuid import uuid4 as _u
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = _u()
    org_id = _u()
    email = f"wf+{_u().hex[:6]}@t.local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user")


# ================================================================ validate =


async def test_validate_happy_yaml(client):
    tok = await _mkuser()
    yaml_doc = """
version: "0.1"
name: "sample-list-drones"
description: "smoke test"
steps:
  - id: s1
    tool: list_drones
    args: {}
"""
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={"workflow_yaml": yaml_doc},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["name"] == "sample-list-drones"
    assert body["steps"] == ["s1"]
    assert body["tools_used"] == ["list_drones"]
    assert body["error"] is None


async def test_validate_happy_json_object(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1",
                "name": "obj-form",
                "steps": [{"id": "a", "tool": "list_drones", "args": {}}],
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_validate_missing_source_400(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={},
    )
    assert r.status_code == 400
    assert "workflow_yaml" in r.text


async def test_validate_both_sources_400(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={
            "workflow_yaml": "version: '0.1'\nname: n\nsteps: []",
            "workflow": {"version": "0.1", "name": "n", "steps": []},
        },
    )
    assert r.status_code == 400
    assert "exactly one" in r.text


async def test_validate_reports_syntax_error(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={"workflow_yaml": ":: invalid: yaml: [unterminated"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error_type"] == "syntax"
    assert body["error"]


async def test_validate_reports_semantic_error_unknown_tool(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "bad-tool",
                "steps": [{"id": "s", "tool": "ghost_tool", "args": {}}],
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error_type"] == "semantic"
    assert "ghost_tool" in body["error"]
    # Even for semantic failures, name should surface (parsing succeeded).
    assert body["name"] == "bad-tool"


async def test_validate_reports_cycle(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "cyc",
                "steps": [
                    {"id": "a", "tool": "list_drones", "args": {},
                     "depends_on": ["b"]},
                    {"id": "b", "tool": "list_drones", "args": {},
                     "depends_on": ["a"]},
                ],
            },
        },
    )
    body = r.json()
    assert body["ok"] is False
    assert body["error_type"] == "semantic"
    assert "cycle" in body["error"]


async def test_validate_allowed_input_keys_enforced(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "inp-check",
                "steps": [{
                    "id": "s", "tool": "list_drones", "args": {},
                }],
            },
            "allowed_input_keys": ["allowed_a", "allowed_b"],
        },
    )
    # No inputs used -> should pass
    assert r.json()["ok"] is True


async def test_validate_requires_auth(client):
    r = await client.post(
        "/api/v1/copilot/workflows/validate",
        json={"workflow_yaml": "version: '0.1'\nname: n\nsteps: []"},
    )
    assert r.status_code in (401, 403)


# ==================================================================== run =


async def test_run_happy_list_drones(client):
    """End-to-end: DSL doc → registry tool → real response."""
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "run-smoke",
                "steps": [{"id": "s1", "tool": "list_drones", "args": {}}],
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["workflow_name"] == "run-smoke"
    assert body["duration_ms"] >= 0
    assert body["error"] is None
    assert len(body["steps"]) == 1
    step = body["steps"][0]
    assert step["id"] == "s1"
    assert step["tool"] == "list_drones"
    assert step["status"] == "ok"
    assert isinstance(step["result"], dict)


async def test_run_returns_400_on_parse_error(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={"workflow_yaml": "::not: yaml: [unclosed"},
    )
    assert r.status_code == 400
    assert "parse" in r.text


async def test_run_returns_400_on_validate_error(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "n",
                "steps": [{"id": "s", "tool": "no_such_tool", "args": {}}],
            },
        },
    )
    assert r.status_code == 400
    assert "validate" in r.text


async def test_run_multi_step_topo_order(client):
    """Two-step chain: a → b; response steps must be topo-ordered."""
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "chain",
                "steps": [
                    {"id": "a", "tool": "list_drones", "args": {}},
                    {"id": "b", "tool": "list_drones", "args": {},
                     "depends_on": ["a"]},
                ],
            },
        },
    )
    body = r.json()
    assert body["status"] == "ok"
    ids = [s["id"] for s in body["steps"]]
    assert ids == ["a", "b"]


async def test_run_requires_auth(client):
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        json={
            "workflow": {
                "version": "0.1", "name": "n",
                "steps": [{"id": "s", "tool": "list_drones", "args": {}}],
            },
        },
    )
    assert r.status_code in (401, 403)


async def test_run_reports_step_failure_as_200_with_failed_status(client):
    """Runtime failures return HTTP 200 with status='failed' + per-step
    diagnostics — the 4xx is reserved for authoring errors only."""
    tok = await _mkuser()
    # Craft a workflow that resolves ${input.x} to a missing key at
    # runtime — this is a *runtime* failure (static validation lets it
    # through when no allowed_input_keys constraint given).
    r = await client.post(
        "/api/v1/copilot/workflows/run",
        headers=_h(tok),
        json={
            "workflow": {
                "version": "0.1", "name": "runtime-miss",
                "steps": [
                    {"id": "s", "tool": "get_drone_status",
                     "args": {"drone_id": "${input.missing_id}"}},
                ],
            },
            "inputs": {},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["steps"][0]["status"] == "failed"
    assert "interpolation" in (body["steps"][0]["error"] or "").lower()
