"""Copilot v2 approval decide endpoint tests — T4.1."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.copilot_approval import CopilotApproval
from app.models.copilot_session import CopilotSession
from app.models.copilot_trace import CopilotTrace
from app.models.drone import Drone
from app.models.user import User
from app.services.auth import hash_password


async def _bootstrap(client, email: str, role: str = "operator"):
    """Create user + session + pending approval; return (token, approval_id, trace_id, drone_id, org_id)."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    async with Session() as s:
        user = User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role, org_id=org_id,
        )
        drone = Drone(
            id=uuid4(), org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        )
        session = CopilotSession(id=uuid4(), org_id=org_id, user_id=user.id)
        s.add_all([user, drone, session])
        await s.commit()

        trace = CopilotTrace(
            id=uuid4(), session_id=session.id, org_id=org_id,
            user_id=user.id, prompt="创建巡逻",
            status="awaiting_approval",
            started_at=datetime.now(timezone.utc),
        )
        s.add(trace)
        await s.commit()

        approval = CopilotApproval(
            id=uuid4(),
            trace_id=trace.id,
            required_reason=json.dumps({
                "tool": "create_mission",
                "arguments": {
                    "name": "巡逻任务",
                    "drone_id": str(drone.id),
                    "waypoints": [[104.06, 30.67, 100]],
                },
                "session_id": str(session.id),
            }, ensure_ascii=False),
        )
        s.add(approval)
        await s.commit()
        approval_id = str(approval.id)
        trace_id = str(trace.id)
        drone_id = str(drone.id)

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    return r.json()["access_token"], approval_id, trace_id, drone_id, str(org_id)


@pytest.mark.asyncio
async def test_v2_approve_executes_tool_and_records_step(client):
    tok, aid, tid, drone_id, _ = await _bootstrap(client, "v2ap_ok@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid}/decide",
        headers=hdrs,
        json={"decision": "approved"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "approved"
    assert body["tool"] == "create_mission"
    assert body["is_error"] is False
    assert body["result"]["status"] == "executed"
    assert body["result"]["output"]["ok"] is True
    assert body["result"]["output"]["status"] == "planned"

    # Second decide should 409
    r2 = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid}/decide",
        headers=hdrs,
        json={"decision": "approved"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_v2_reject_skips_execution(client):
    tok, aid, tid, _, _ = await _bootstrap(client, "v2ap_rej@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid}/decide",
        headers=hdrs,
        json={"decision": "rejected", "comment": "太危险"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "rejected"
    assert body["result"]["status"] == "rejected"
    assert body["is_error"] is False


@pytest.mark.asyncio
async def test_v2_modified_uses_updated_args(client):
    tok, aid, tid, drone_id, _ = await _bootstrap(client, "v2ap_mod@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid}/decide",
        headers=hdrs,
        json={
            "decision": "modified",
            "modifications": {"name": "改名后的巡逻"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "modified"
    assert body["arguments"]["name"] == "改名后的巡逻"
    assert body["result"]["output"]["name"] == "改名后的巡逻"


@pytest.mark.asyncio
async def test_v2_approval_unknown_returns_404(client):
    tok, _, _, _, _ = await _bootstrap(client, "v2ap_404@x.com")
    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{uuid4()}/decide",
        headers={"Authorization": f"Bearer {tok}"},
        json={"decision": "approved"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_v2_approval_bad_decision_rejected_by_pydantic(client):
    tok, aid, _, _, _ = await _bootstrap(client, "v2ap_bad@x.com")
    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid}/decide",
        headers={"Authorization": f"Bearer {tok}"},
        json={"decision": "yolo"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_v2_pending_list_returns_approvals(client):
    tok, aid, tid, _, _ = await _bootstrap(client, "v2ap_list@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.get("/api/v1/copilot/v2/approvals/pending", headers=hdrs)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    ours = [it for it in items if it["approval_id"] == aid]
    assert len(ours) == 1
    assert ours[0]["tool"] == "create_mission"
    assert ours[0]["trace_id"] == tid
    assert ours[0]["prompt"] == "创建巡逻"


@pytest.mark.asyncio
async def test_v2_pending_list_org_scope(client):
    """A user from another org shouldn't see pending approvals from other orgs."""
    tok_a, aid, _, _, _ = await _bootstrap(client, "v2ap_scope_a@x.com")
    tok_b, aid_b, _, _, _ = await _bootstrap(client, "v2ap_scope_b@x.com")

    r_a = await client.get(
        "/api/v1/copilot/v2/approvals/pending",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    a_ids = {it["approval_id"] for it in r_a.json()}
    assert aid in a_ids
    assert aid_b not in a_ids


@pytest.mark.asyncio
async def test_v2_cross_org_decide_forbidden(client):
    """A user cannot approve another org's approval."""
    tok_a, aid_a, _, _, _ = await _bootstrap(client, "v2ap_xorg_a@x.com")
    tok_b, _, _, _, _ = await _bootstrap(client, "v2ap_xorg_b@x.com")

    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{aid_a}/decide",
        headers={"Authorization": f"Bearer {tok_b}"},
        json={"decision": "approved"},
    )
    assert r.status_code == 403
