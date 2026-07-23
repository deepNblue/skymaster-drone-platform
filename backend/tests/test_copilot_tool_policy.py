"""F4.4 · Copilot tool policy + audit tests."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.copilot_tool_policy import (
    evaluate as policy_evaluate,
    record_audit,
    upsert_policy,
)


pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(
    role: str = "user", org_id: UUID | None = None,
) -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = org_id or uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"{role}+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return (
        create_access_token(user_id=uid, org_id=org, role=role),
        uid, org,
    )


async def _session():
    return async_sessionmaker(engine, expire_on_commit=False)


# ================ ToolSpec risk_level baseline ================

async def test_readonly_tool_default_allowed(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        dec = await policy_evaluate(s, org_id=org, tool_name="list_drones")
    assert dec.action == "allowed"
    assert dec.permission == "readonly"
    assert dec.risk_level in ("low", "medium", "high", "critical")


async def test_sensitive_tool_requires_approval(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        dec = await policy_evaluate(s, org_id=org, tool_name="dispatch_mission")
    assert dec.action == "approval_required"
    assert dec.permission == "sensitive"
    assert dec.risk_level == "critical"


async def test_unknown_tool_blocked(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        dec = await policy_evaluate(s, org_id=org, tool_name="nope_never_exists")
    assert dec.action == "blocked"


# ================ Policy configuration ================

async def test_blocklist_wins(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        await upsert_policy(
            s, org_id=org,
            allowlist=None, blocklist=["list_drones"],
            max_risk_level=None, require_approval_above=None,
        )
    async with S() as s:
        dec = await policy_evaluate(s, org_id=org, tool_name="list_drones")
    assert dec.action == "blocked"
    assert "blocklist" in (dec.reason or "")


async def test_allowlist_gates_other_tools(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        await upsert_policy(
            s, org_id=org,
            allowlist=["list_drones"], blocklist=None,
            max_risk_level=None, require_approval_above=None,
        )
    async with S() as s:
        allowed = await policy_evaluate(s, org_id=org, tool_name="list_drones")
        blocked = await policy_evaluate(s, org_id=org, tool_name="check_airspace")
    assert allowed.action == "allowed"
    assert blocked.action == "blocked"


async def test_max_risk_level_blocks_higher(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        await upsert_policy(
            s, org_id=org,
            allowlist=None, blocklist=None,
            max_risk_level="medium",
            require_approval_above=None,
        )
    async with S() as s:
        dec = await policy_evaluate(s, org_id=org, tool_name="dispatch_mission")
    assert dec.action == "blocked"
    assert "exceeds" in (dec.reason or "")


async def test_require_approval_above_promotes_readonly(client) -> None:
    """Even a readonly tool goes through approval if its risk >= gate."""
    _, _, org = await _mkuser()
    # Temporarily bump a readonly tool's risk to test the gate
    from app.services.tool_registry import get_registry
    reg = get_registry()
    spec = reg.get("check_airspace")
    original = spec.risk_level
    spec.risk_level = "high"
    try:
        S = await _session()
        async with S() as s:
            await upsert_policy(
                s, org_id=org,
                allowlist=None, blocklist=None,
                max_risk_level=None,
                require_approval_above="high",
            )
        async with S() as s:
            dec = await policy_evaluate(
                s, org_id=org, tool_name="check_airspace",
            )
        assert dec.action == "approval_required"
    finally:
        spec.risk_level = original


async def test_policy_upsert_idempotent(client) -> None:
    _, _, org = await _mkuser()
    S = await _session()
    async with S() as s:
        p1 = await upsert_policy(
            s, org_id=org,
            allowlist=["list_drones"], blocklist=None,
            max_risk_level="high", require_approval_above=None,
        )
    async with S() as s:
        p2 = await upsert_policy(
            s, org_id=org,
            allowlist=None, blocklist=["abort_mission"],
            max_risk_level="critical", require_approval_above="high",
        )
    assert p1.id == p2.id
    assert p2.blocklist == ["abort_mission"]
    assert p2.max_risk_level == "critical"


# ================ Audit write ================

async def test_record_audit_writes_row(client) -> None:
    _, uid, org = await _mkuser()
    S = await _session()
    async with S() as s:
        row = await record_audit(
            s,
            org_id=org, user_id=uid,
            tool_name="list_drones",
            status="executed",
            permission="readonly", risk_level="low",
            arguments={"limit": 10},
            result={"drones": []},
            latency_ms=45,
        )
    assert row.id is not None
    assert row.status == "executed"
    assert row.tool_name == "list_drones"


async def test_record_audit_truncates_long_result(client) -> None:
    _, uid, org = await _mkuser()
    S = await _session()
    async with S() as s:
        row = await record_audit(
            s,
            org_id=org, user_id=uid,
            tool_name="list_drones",
            status="executed",
            permission="readonly", risk_level="low",
            result={"data": "x" * 5000},
        )
    assert row.result_preview is not None
    assert len(row.result_preview) <= 500


# ================ REST API ================

async def test_get_my_policy_empty(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get("/api/v1/copilot/tool-policy/me", headers=_h(tok))
    assert r.status_code == 200
    assert r.json() is None


async def test_put_my_policy_roundtrip(client) -> None:
    tok, _, _ = await _mkuser()
    body = {
        "allowlist": ["list_drones", "check_airspace"],
        "blocklist": ["abort_mission"],
        "max_risk_level": "high",
        "require_approval_above": "medium",
    }
    r = await client.put(
        "/api/v1/copilot/tool-policy/me", headers=_h(tok), json=body,
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["allowlist"] == body["allowlist"]
    assert got["max_risk_level"] == "high"

    # Round-trip via GET
    r2 = await client.get("/api/v1/copilot/tool-policy/me", headers=_h(tok))
    assert r2.json()["blocklist"] == ["abort_mission"]


async def test_put_policy_rejects_unknown_tool(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.put(
        "/api/v1/copilot/tool-policy/me", headers=_h(tok),
        json={"blocklist": ["totally_fake_tool"]},
    )
    assert r.status_code == 400


async def test_put_policy_rejects_bad_tier(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.put(
        "/api/v1/copilot/tool-policy/me", headers=_h(tok),
        json={"max_risk_level": "extreme"},
    )
    assert r.status_code == 400


async def test_tool_catalog(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get("/api/v1/copilot/tool-policy/tools", headers=_h(tok))
    assert r.status_code == 200
    tools = r.json()
    assert len(tools) >= 4
    names = {t["name"] for t in tools}
    assert "dispatch_mission" in names
    disp = next(t for t in tools if t["name"] == "dispatch_mission")
    assert disp["risk_level"] == "critical"


async def test_audit_endpoints(client) -> None:
    tok, uid, org = await _mkuser()
    S = await _session()
    async with S() as s:
        await record_audit(
            s, org_id=org, user_id=uid,
            tool_name="list_drones", status="executed",
            permission="readonly", risk_level="low",
        )
        await record_audit(
            s, org_id=org, user_id=uid,
            tool_name="dispatch_mission", status="approval_required",
            permission="sensitive", risk_level="critical",
        )

    r = await client.get("/api/v1/copilot/tool-policy/audits", headers=_h(tok))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2

    r2 = await client.get(
        "/api/v1/copilot/tool-policy/audits",
        headers=_h(tok),
        params={"status": "approval_required"},
    )
    assert all(x["status"] == "approval_required" for x in r2.json())

    r3 = await client.get(
        "/api/v1/copilot/tool-policy/audits/stats", headers=_h(tok),
    )
    assert r3.status_code == 200
    stats = r3.json()
    assert "executed" in stats or "approval_required" in stats


async def test_org_audit_isolation(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    _tok_b, uid_b, org_b = await _mkuser()
    S = await _session()
    async with S() as s:
        await record_audit(
            s, org_id=org_a, user_id=uid_a,
            tool_name="list_drones", status="executed",
            permission="readonly", risk_level="low",
        )
        await record_audit(
            s, org_id=org_b, user_id=uid_b,
            tool_name="dispatch_mission", status="blocked",
            permission="sensitive", risk_level="critical",
            reason="on blocklist",
        )
    r = await client.get("/api/v1/copilot/tool-policy/audits", headers=_h(tok_a))
    rows = r.json()
    tools = {row["tool_name"] for row in rows}
    assert "list_drones" in tools
    assert "dispatch_mission" not in tools  # other org's row hidden
