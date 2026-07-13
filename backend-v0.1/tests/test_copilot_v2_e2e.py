"""End-to-end integration test for Copilot v2 → T4.3.

Runs the full backend stack (real DB, real routing, real tool
registry) against a mocked LLM. We bypass the SSE endpoint's
httpx-ASGI streaming (which hangs in the test transport) and
instead invoke ``CopilotAgentV2.run()`` directly to enqueue an
approval, then exercise the approval decide endpoint over HTTP.

This still covers the T4.3 objective: the full approve → dispatch
loop with real DB side effects and a real HTTP client on the
critical decide path.

Scenarios covered:
1. approve → tool actually runs → Mission row exists → trace 'approved'
2. reject → no Mission row → trace 'rejected'
3. modified → Mission uses operator-overridden args
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.copilot_approval import CopilotApproval
from app.models.copilot_session import CopilotSession
from app.models.copilot_trace import CopilotTrace
from app.models.copilot_trace_step import CopilotTraceStep
from app.models.drone import Drone
from app.models.mission import Mission
from app.models.user import User
from app.services.auth import hash_password
from app.services.copilot_agent_v2 import AgentConfig, CopilotAgentV2
from app.services.tool_registry import ToolContext, build_default_registry


async def _bootstrap(client, email: str):
    from app.db import engine
    from app.services.auth import create_access_token

    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    async with Session() as s:
        u = User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role="operator", org_id=org_id,
        )
        drone = Drone(
            id=uuid4(), org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        )
        sess = CopilotSession(id=uuid4(), org_id=org_id, user_id=u.id)
        s.add_all([u, drone, sess])
        await s.commit()
        sid = sess.id
        drone_id = drone.id
        user_id = u.id

    # Avoid the /auth/login rate-limiter by minting a token directly.
    tok = create_access_token(user_id=user_id, org_id=org_id, role="operator")
    return tok, sid, drone_id, org_id, user_id


async def _run_agent_and_enqueue(
    session_id, org_id, user_id, drone_id, mission_name: str,
) -> str:
    """Run the v2 agent with a scripted LLM to enqueue a create_mission approval.

    Returns the approval_id (str).
    """
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)

    fake_llm = AsyncMock()
    fake_llm.protocol = "anthropic"
    fake_llm.chat_completion = AsyncMock(return_value={
        "stop_reason": "tool_use",
        "content": [{
            "type": "tool_use", "id": "tu_1",
            "name": "create_mission",
            "input": {
                "name": mission_name,
                "drone_id": str(drone_id),
                "waypoints": [[104.06, 30.67, 100]],
            },
        }],
    })
    agent = CopilotAgentV2(fake_llm, build_default_registry(), AgentConfig())

    emitted: list[dict] = []

    async def emit(evt: dict) -> None:
        emitted.append(evt)

    async with Session() as db:
        # Create a trace row like the endpoint does
        trace = CopilotTrace(
            id=uuid4(),
            session_id=session_id, org_id=org_id, user_id=user_id,
            prompt=f"创建 {mission_name}", status="running",
        )
        db.add(trace)
        await db.commit()
        await db.refresh(trace)

        ctx = ToolContext(db=db, org_id=org_id, user_id=user_id)
        result = await agent.run(
            f"创建 {mission_name}", history=None, ctx=ctx,
            emit_cb=emit,
            session_id=session_id, trace_id=trace.id, db=db,
        )
        trace.status = "awaiting_approval"
        trace.output = {
            "text": result.get("text") or "",
            "tool_calls": result.get("tool_calls") or [],
            "pending_approvals": result.get("pending_approvals") or [],
            "stopped_reason": result.get("stopped_reason"),
        }
        await db.commit()

    assert result["stopped_reason"] == "approval_required"
    assert len(result["pending_approvals"]) == 1
    return result["pending_approvals"][0]


@pytest.mark.asyncio
async def test_copilot_v2_e2e_approval_loop(client):
    """Approve path — tool actually runs; Mission row created."""
    tok, sid, drone_id, org_id, user_id = await _bootstrap(client, "cv2_e2e@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}

    approval_id = await _run_agent_and_enqueue(
        sid, org_id, user_id, drone_id, "E2E巡逻",
    )

    # List via HTTP
    r = await client.get("/api/v1/copilot/v2/approvals/pending", headers=hdrs)
    assert r.status_code == 200
    pending = r.json()
    assert len(pending) >= 1
    ours = next(p for p in pending if p["approval_id"] == approval_id)
    assert ours["tool"] == "create_mission"
    assert ours["session_id"] == str(sid)
    assert ours["arguments"]["drone_id"] == str(drone_id)

    # Approve via HTTP
    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{approval_id}/decide",
        headers=hdrs, json={"decision": "approved"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "approved"
    assert body["is_error"] is False
    assert body["result"]["status"] == "executed"
    assert body["result"]["output"]["ok"] is True
    assert body["result"]["output"]["status"] == "planned"
    mission_id = body["result"]["output"]["mission_id"]

    # DB assertions
    from app.db import engine
    from uuid import UUID as _UUID
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == _UUID(mission_id)))).scalar_one()
        assert str(m.drone_id) == str(drone_id)
        assert m.name == "E2E巡逻"
        assert m.status == "planned"

        ap = (
            await db.execute(select(CopilotApproval).where(CopilotApproval.id == _UUID(approval_id)))
        ).scalar_one()
        assert ap.decision == "approved"

        trace = (
            await db.execute(select(CopilotTrace).where(CopilotTrace.id == ap.trace_id))
        ).scalar_one()
        assert trace.status == "approved"

        steps = (
            await db.execute(
                select(CopilotTraceStep)
                .where(CopilotTraceStep.trace_id == trace.id)
                .order_by(CopilotTraceStep.idx)
            )
        ).scalars().all()
        tools = [s.tool for s in steps]
        # Agent persists an llm_call step + one step per approval (labeled by tool
        # name in current impl); /decide adds another create_mission step for the
        # actual execution.
        assert "llm_call" in tools
        assert tools.count("create_mission") >= 2


@pytest.mark.asyncio
async def test_copilot_v2_e2e_reject_no_side_effect(client):
    """Reject path — no Mission row created."""
    tok, sid, drone_id, org_id, user_id = await _bootstrap(client, "cv2_e2e_rej@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}

    approval_id = await _run_agent_and_enqueue(
        sid, org_id, user_id, drone_id, "被驳回巡逻",
    )

    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{approval_id}/decide",
        headers=hdrs,
        json={"decision": "rejected", "comment": "空域冲突"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "rejected"
    assert body["result"]["status"] == "rejected"

    from app.db import engine
    from uuid import UUID as _UUID
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        rows = (
            await db.execute(select(Mission).where(Mission.name == "被驳回巡逻"))
        ).scalars().all()
        assert rows == []

        ap = (
            await db.execute(select(CopilotApproval).where(CopilotApproval.id == _UUID(approval_id)))
        ).scalar_one()
        assert ap.decision == "rejected"
        assert ap.comment == "空域冲突"

        trace = (
            await db.execute(select(CopilotTrace).where(CopilotTrace.id == ap.trace_id))
        ).scalar_one()
        assert trace.status == "rejected"


@pytest.mark.asyncio
async def test_copilot_v2_e2e_modified_uses_new_args(client):
    """Modified path — Mission uses operator's overridden name."""
    tok, sid, drone_id, org_id, user_id = await _bootstrap(client, "cv2_e2e_mod@x.com")
    hdrs = {"Authorization": f"Bearer {tok}"}

    approval_id = await _run_agent_and_enqueue(
        sid, org_id, user_id, drone_id, "原始名字",
    )

    r = await client.post(
        f"/api/v1/copilot/v2/approvals/{approval_id}/decide",
        headers=hdrs,
        json={
            "decision": "modified",
            "modifications": {"name": "指挥员改名后的任务"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "modified"
    assert body["arguments"]["name"] == "指挥员改名后的任务"
    mid = body["result"]["output"]["mission_id"]

    from app.db import engine
    from uuid import UUID as _UUID
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        m = (await db.execute(select(Mission).where(Mission.id == _UUID(mid)))).scalar_one()
        assert m.name == "指挥员改名后的任务"

        rows = (
            await db.execute(select(Mission).where(Mission.name == "原始名字"))
        ).scalars().all()
        assert rows == []
