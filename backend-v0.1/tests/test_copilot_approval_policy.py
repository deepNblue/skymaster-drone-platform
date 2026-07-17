"""E2.5 · 双签/多签审批策略测试."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_approval import CopilotApproval
from app.models.user import User
from app.services import copilot_approval_policy as svc
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(role: str = "admin") -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"ap+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid, org


async def _mksign(org: UUID, role: str) -> tuple[str, UUID]:
    uid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"sg+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid


async def _mkapproval(trace_id: UUID | None = None) -> UUID:
    """Create a bare CopilotApproval row and return its id."""
    aid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotApproval(
            id=aid,
            trace_id=trace_id or uuid4(),
            required_reason='{"tool":"dispatch_mission"}',
        ))
        await s.commit()
    return aid


# ============ Service layer ============

async def test_default_policy_is_single_sign(client) -> None:
    _, _, org = await _mkuser()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        req = await svc.evaluate_requirement(
            s, org_id=org, tool_name="dispatch_mission", risk_level="high",
        )
    assert req.needs_signs == 1


async def test_dual_sign_by_tool_list(client) -> None:
    _, uid, org = await _mkuser()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid,
            dual_sign_tools=["abort_mission", "batch_delete_drones"],
        )
        req = await svc.evaluate_requirement(
            s, org_id=org, tool_name="abort_mission", risk_level="low",
        )
    assert req.needs_signs == 2
    assert "dual_sign_tools" in req.reason


async def test_dual_sign_by_risk_threshold(client) -> None:
    _, uid, org = await _mkuser()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid,
            dual_sign_min_risk="high",
        )
        req_low = await svc.evaluate_requirement(
            s, org_id=org, tool_name="x", risk_level="medium",
        )
        req_high = await svc.evaluate_requirement(
            s, org_id=org, tool_name="x", risk_level="high",
        )
        req_crit = await svc.evaluate_requirement(
            s, org_id=org, tool_name="x", risk_level="critical",
        )
    assert req_low.needs_signs == 1
    assert req_high.needs_signs == 2
    assert req_crit.needs_signs == 2


async def test_signoff_single_sign_approve(client) -> None:
    _, uid, org = await _mkuser()
    aid = await _mkapproval()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        r = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid, signer_role="admin",
            decision="approve", tool_name="dispatch_mission", risk_level="medium",
        )
    assert r.final_decision == "approve"
    assert r.needs_signs == 1
    assert r.done_signs == 1

    # Verify propagated to CopilotApproval row
    async with S() as s:
        from sqlalchemy import select
        res = await s.execute(select(CopilotApproval).where(CopilotApproval.id == aid))
        approval = res.scalar_one()
    assert approval.decision == "approve"
    assert approval.approver_id == uid


async def test_signoff_dual_sign_flow(client) -> None:
    _, uid1, org = await _mkuser(role="admin")
    _, uid2 = await _mksign(org, role="compliance")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid1,
            dual_sign_tools=["abort_mission"],
        )

    aid = await _mkapproval()
    async with S() as s:
        r1 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid1, signer_role="admin",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
    assert r1.final_decision is None  # still pending
    assert r1.needs_signs == 2
    assert r1.done_signs == 1

    async with S() as s:
        r2 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid2, signer_role="compliance",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
    assert r2.final_decision == "approve"
    assert r2.done_signs == 2


async def test_signoff_reject_short_circuits(client) -> None:
    _, uid1, org = await _mkuser(role="admin")
    _, uid2 = await _mksign(org, role="compliance")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid1,
            dual_sign_tools=["abort_mission"],
        )

    aid = await _mkapproval()
    async with S() as s:
        r1 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid1, signer_role="admin",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
        assert r1.final_decision is None
        r2 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid2, signer_role="compliance",
            decision="reject", comment="风险太高", tool_name="abort_mission",
            risk_level="high",
        )
    assert r2.final_decision == "reject"


async def test_signoff_duplicate_signer_rejected(client) -> None:
    _, uid, org = await _mkuser()
    aid = await _mkapproval()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid,
            dual_sign_tools=["abort_mission"],
        )
        await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid, signer_role="admin",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
        with pytest.raises(ValueError, match="already signed"):
            await svc.add_signoff(
                s, approval_id=aid, org_id=org, signer_id=uid, signer_role="admin",
                decision="approve", tool_name="abort_mission", risk_level="high",
            )


async def test_signoff_required_roles_enforced(client) -> None:
    _, uid1, org = await _mkuser(role="admin")
    _, uid2 = await _mksign(org, role="admin")   # not a compliance officer
    _, uid3 = await _mksign(org, role="compliance")

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await svc.upsert_policy(
            s, org_id=org, updated_by=uid1,
            dual_sign_tools=["abort_mission"],
            required_roles=["admin", "compliance"],
        )

    aid = await _mkapproval()
    async with S() as s:
        r1 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid1, signer_role="admin",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
        r2 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid2, signer_role="admin",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
    # Two admins but no compliance → still not finalized despite 2 approves
    assert r2.final_decision is None
    assert r2.done_signs == 2

    async with S() as s:
        r3 = await svc.add_signoff(
            s, approval_id=aid, org_id=org, signer_id=uid3, signer_role="compliance",
            decision="approve", tool_name="abort_mission", risk_level="high",
        )
    assert r3.final_decision == "approve"


# ============ REST API ============

async def test_api_upsert_and_get_policy(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.put(
        "/api/v1/copilot/approval-policy/me", headers=_h(tok),
        json={
            "dual_sign_tools": ["abort_mission"],
            "dual_sign_min_risk": "high",
            "required_roles": ["admin", "compliance"],
        },
    )
    assert r.status_code == 200, r.text
    got = await client.get(
        "/api/v1/copilot/approval-policy/me", headers=_h(tok),
    )
    assert got.status_code == 200
    body = got.json()
    assert body["dual_sign_min_risk"] == "high"
    assert "abort_mission" in body["dual_sign_tools"]


async def test_api_invalid_risk_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.put(
        "/api/v1/copilot/approval-policy/me", headers=_h(tok),
        json={"dual_sign_min_risk": "supersonic"},
    )
    assert r.status_code == 400


async def test_api_signoff_and_status(client) -> None:
    tok, uid, org = await _mkuser(role="admin")
    aid = await _mkapproval()

    # Configure single-sign scenario (default)
    r = await client.post(
        f"/api/v1/copilot/approval-policy/approvals/{aid}/sign",
        headers=_h(tok),
        json={
            "decision": "approve", "tool_name": "list_drones",
            "risk_level": "low",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_decision"] == "approve"
    assert body["needs_signs"] == 1

    status = await client.get(
        f"/api/v1/copilot/approval-policy/approvals/{aid}/status",
        headers=_h(tok),
        params={"tool_name": "list_drones", "risk_level": "low"},
    )
    assert status.status_code == 200
    s_body = status.json()
    assert s_body["final_decision"] == "approve"
    assert len(s_body["signoffs"]) == 1


async def test_api_org_isolation(client) -> None:
    tok_a, _, org_a = await _mkuser()
    tok_b, _, org_b = await _mkuser()
    r = await client.put(
        "/api/v1/copilot/approval-policy/me", headers=_h(tok_a),
        json={"dual_sign_tools": ["private_tool"]},
    )
    assert r.status_code == 200

    r_b = await client.get(
        "/api/v1/copilot/approval-policy/me", headers=_h(tok_b),
    )
    assert r_b.status_code == 200
    assert r_b.json() is None
