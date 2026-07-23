"""T5.5 — Copilot tools for flight approvals + RPA bridge.

Wraps the T7.1 bridge behind the same tenant-scoped, permission-checked
tool contract every other Copilot tool uses.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email: str, role: str = "user"):
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


async def _mkuser_in_org(email: str, org_id, role: str = "user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    uid = uuid4()
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


@pytest.fixture(autouse=True)
def _reset_bridge():
    from app.services.rpa_bridge import get_bridge
    get_bridge()._reset()
    yield
    get_bridge()._reset()


async def _new_approval_in_review(client, op_tok, sup_tok):
    """Draft → high-alt submit → supervisor approves → in_review."""
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "t55 flight",
            "purpose": "航测",
            "category": "routine",
            "aircraft_reg": "N-T55",
            "aircraft_model": "M300",
            "max_alt_m": 200,
            "area_polygon": [
                [104.0, 30.6], [104.02, 30.6],
                [104.02, 30.62], [104.0, 30.62],
            ],
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
        headers=_h(op_tok),
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = await client.post(f"/api/v1/approvals/{aid}/submit", headers=_h(op_tok))
    assert r.status_code == 200
    r = await client.post(
        f"/api/v1/approvals/{aid}/second-approval?aircraft_weight_kg=6",
        json={"decision": "approve"},
        headers=_h(sup_tok),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_tool_registry_lists_new_tools():
    from app.services.tool_registry import build_default_registry
    r = build_default_registry()
    names = {t.name for t in r._tools.values()}
    assert "list_approvals" in names
    assert "dispatch_rpa_authority" in names
    dispatch = r._tools["dispatch_rpa_authority"]
    assert dispatch is not None
    # Sensitive → user approval required in the agent loop
    assert dispatch.permission == "sensitive"


@pytest.mark.asyncio
async def test_list_approvals_tool_is_tenant_scoped(client):
    from app.db import engine
    from app.services.tool_registry import (
        ListApprovalsArgs, ToolContext, list_approvals,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    op_tok, _, org_a = await _mkuser("op-a@t55.com")
    sup_tok, _ = await _mkuser_in_org("sup-a@t55.com", org_a, role="supervisor")
    await _new_approval_in_review(client, op_tok, sup_tok)

    # A different org exists but has no approvals — must see zero.
    _, _, org_b = await _mkuser("op-b@t55.com")

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        result_a = await list_approvals(
            ToolContext(db=s, org_id=org_a), ListApprovalsArgs(),
        )
        result_b = await list_approvals(
            ToolContext(db=s, org_id=org_b), ListApprovalsArgs(),
        )
    assert result_a["count"] >= 1
    assert result_b["count"] == 0
    # Tenant leak-check: no id from org A appears in org B's result
    ids_a = {a["id"] for a in result_a["approvals"]}
    ids_b = {a["id"] for a in result_b["approvals"]}
    assert not (ids_a & ids_b)


@pytest.mark.asyncio
async def test_dispatch_rpa_authority_tool(client):
    from app.db import engine
    from app.services.tool_registry import (
        DispatchRpaAuthorityArgs, ToolContext, dispatch_rpa_authority,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    op_tok, _, org = await _mkuser("op-r@t55.com")
    sup_tok, _ = await _mkuser_in_org("sup-r@t55.com", org, role="supervisor")
    approval = await _new_approval_in_review(client, op_tok, sup_tok)
    rpa_rows = [a for a in approval["authorities"] if a["channel"] == "rpa"]
    if not rpa_rows:
        pytest.skip(f"no rpa-channel authority; got {approval['authorities']}")
    rpa_target = rpa_rows[0]

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        # First dispatch — creates a job
        r1 = await dispatch_rpa_authority(
            ToolContext(db=s, org_id=org),
            DispatchRpaAuthorityArgs(
                approval_id=approval["id"],
                authority_code=rpa_target["authority_code"],
            ),
        )
        # Second call — idempotent
        r2 = await dispatch_rpa_authority(
            ToolContext(db=s, org_id=org),
            DispatchRpaAuthorityArgs(
                approval_id=approval["id"],
                authority_code=rpa_target["authority_code"],
            ),
        )
    assert r1["ok"] is True
    assert r1["job_id"]
    assert r1["driver"] in ("mock", "shenzhen_atc_eform")
    assert r2["job_id"] == r1["job_id"]

    # Wrong org → rejected
    _, _, org_x = await _mkuser("other@t55.com")
    async with S() as s:
        r3 = await dispatch_rpa_authority(
            ToolContext(db=s, org_id=org_x),
            DispatchRpaAuthorityArgs(
                approval_id=approval["id"],
                authority_code=rpa_target["authority_code"],
            ),
        )
    assert r3["ok"] is False
    assert "not found" in r3["reason"]


@pytest.mark.asyncio
async def test_dispatch_rejects_non_rpa_authority(client):
    """Only channel='rpa' rows are dispatch-able — API channels stay
    the router's job."""
    from app.db import engine
    from app.services.tool_registry import (
        DispatchRpaAuthorityArgs, ToolContext, dispatch_rpa_authority,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    op_tok, _, org = await _mkuser("op-api@t55.com")
    sup_tok, _ = await _mkuser_in_org("sup-api@t55.com", org, role="supervisor")
    approval = await _new_approval_in_review(client, op_tok, sup_tok)
    api_row = next(
        (a for a in approval["authorities"] if a["channel"] == "api"), None,
    )
    if api_row is None:
        pytest.skip("no api-channel authority on this approval")

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        r = await dispatch_rpa_authority(
            ToolContext(db=s, org_id=org),
            DispatchRpaAuthorityArgs(
                approval_id=approval["id"],
                authority_code=api_row["authority_code"],
            ),
        )
    assert r["ok"] is False
    assert "not 'rpa'" in r["reason"]
