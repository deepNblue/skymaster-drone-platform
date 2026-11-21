"""E2 integration regression — full L3 Copilot flow in-process.

Uses the same async httpx client as unit tests, but exercises the
end-to-end path:

    autoCreate (LLM planner mock) → run → paused-on-approval
    → decide (approved) → resume → completed → task_history writeback

No SITL / no external services. LLM is monkeypatched to a deterministic
planner so this stays hermetic and fast.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.services.auth import create_access_token, hash_password
from app.models.copilot_memory import CopilotMemory
from app.models.copilot_task_chain import CopilotTaskChainApproval
from app.models.user import User


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(role: str = "user") -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"e2e+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid, org


async def _mkuser_in_org(role: str, org: UUID) -> tuple[str, UUID]:
    uid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"e2e+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid


# ------------------------------------------------------------------
# Full L3 loop
# ------------------------------------------------------------------
async def test_e2_full_l3_copilot_loop(client, monkeypatch) -> None:
    """The complete v2.1 L3 story in one test:

    1. User asks Copilot to do something risky.
    2. LLM planner (mocked) returns a 2-step plan whose second step is
       a `sensitive` tool.
    3. runChain executes step #1 successfully, then pauses on approval.
    4. Admin approves with modified args.
    5. Resume kicks off — step #2 re-runs (fails at tool level with
       intentionally minimal args, which is fine; we only assert flow).
    6. Chain reaches terminal state → task_history memory is upserted.
    """
    # ---- 1. mock LLM planner deterministically ----
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_plan(*, goal, registry, llm, model=None, extra_hint=None):
        return planner_svc.PlanResult(
            subtasks=[
                {"title": "先看机队", "tool": "list_drones", "args": {}, "why": "确认可用无人机"},
                {"title": "下发任务", "tool": "create_mission",
                 "args": {"name": "e2e-m", "waypoints": []}, "why": "创建巡检任务"},
            ],
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "plan", fake_plan)

    # ---- 2. user creates via /auto (LLM-driven) ----
    tok, uid, org = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains/auto",
        headers=_h(tok),
        json={"goal": "帮我检查机队后下发一个巡检任务"},
    )
    assert r.status_code == 200, r.text
    chain = r.json()
    cid = chain["id"]
    assert chain["status"] == "draft"
    assert len(chain["plan_json"]) == 2

    # ---- 3. run to end — should stop at step #2 approval ----
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/run?max_steps=5",
        headers=_h(tok),
    )
    body = r.json()
    assert r.status_code == 200
    assert body["chain"]["status"] == "paused"
    assert body["chain"]["current_index"] == 1

    # ---- 4. verify approval was created ----
    r = await client.get(
        f"/api/v1/copilot/task-chains/{cid}/approvals",
        headers=_h(tok),
    )
    items = r.json()["items"]
    assert len(items) == 1
    approval = items[0]
    assert approval["status"] == "pending"
    assert approval["tool_name"] == "create_mission"
    assert approval["permission"] == "sensitive"

    # Pending list scoped to org
    r = await client.get(
        "/api/v1/copilot/task-chains/approvals/pending",
        headers=_h(tok),
    )
    assert len(r.json()["items"]) == 1

    # ---- 5. admin approves with modified args ----
    admin_tok, admin_uid = await _mkuser_in_org("admin", org)
    r = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{approval['id']}/decide?resume=true",
        headers=_h(admin_tok),
        json={
            "decision": "approved",
            "reason": "已确认巡检半径 500m 合规",
            "modifications": {"name": "e2e-m-approved", "waypoints": []},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval"]["status"] == "approved"
    assert body["approval"]["approver_id"] == str(admin_uid)
    assert body["approval"]["modifications"]["name"] == "e2e-m-approved"

    # ---- 5b. drain remaining steps (resume only advanced once) ----
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/run?max_steps=5", headers=_h(tok),
    )

    # ---- 6. chain should be terminal (either completed or failed) ----
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    assert detail["chain"]["status"] in ("completed", "failed")

    # ---- 7. verify plan_json got updated with approved args ----
    approved_plan = detail["chain"]["plan_json"]
    assert approved_plan[1]["args"]["name"] == "e2e-m-approved"

    # ---- 8. task_history writeback exists ----
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        res = await s.execute(
            select(CopilotMemory).where(
                CopilotMemory.key == f"task_chain:{cid}",
                CopilotMemory.org_id == org,
            )
        )
        mem = res.scalar_one_or_none()
    assert mem is not None
    assert mem.kind == "task_history"
    assert "帮我检查机队后下发一个巡检任务" in mem.content
    # step markers: at least one ✓ (step #1 succeeded)
    assert "✓" in mem.content
    assert mem.meta["chain_id"] == cid


# ------------------------------------------------------------------
# Reject path
# ------------------------------------------------------------------
async def test_e2_reject_path_terminates_chain(client, monkeypatch) -> None:
    """Rejection must fail the chain and still write task_history."""
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_plan(*, goal, registry, llm, model=None, extra_hint=None):
        return planner_svc.PlanResult(
            subtasks=[
                {"title": "危险动作", "tool": "create_mission",
                 "args": {"name": "danger", "waypoints": []}, "why": "test"},
            ],
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "plan", fake_plan)

    tok, _, org = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains/auto",
        headers=_h(tok), json={"goal": "risky path"},
    )
    cid = r.json()["id"]

    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        res = await s.execute(
            select(CopilotTaskChainApproval).where(
                CopilotTaskChainApproval.chain_id == UUID(cid),
            )
        )
        approval = res.scalar_one()

    admin_tok, _ = await _mkuser_in_org("owner", org)
    r = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{approval.id}/decide?resume=false",
        headers=_h(admin_tok),
        json={"decision": "rejected", "reason": "太危险"},
    )
    assert r.status_code == 200

    # Chain failed
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    assert detail["chain"]["status"] == "failed"
    assert "rejected" in detail["chain"]["error"]

    # Writeback exists with failed status
    async with S() as s:
        res = await s.execute(
            select(CopilotMemory).where(
                CopilotMemory.key == f"task_chain:{cid}",
            )
        )
        mem = res.scalar_one_or_none()
    assert mem is not None
    assert "failed" in mem.content


# ------------------------------------------------------------------
# Reflect during a stuck chain (LLM detects off-track and revises)
# ------------------------------------------------------------------
async def test_e2_reflect_appends_recovery_step(client, monkeypatch) -> None:
    """Simulate: chain fails on step #1, user hits /reflect, LLM appends a
    recovery plan, apply=true persists a revision + updates plan_json."""
    from app.services import copilot_task_chain_planner as planner_svc

    # Reflect returns an append_step suggestion
    async def fake_reflect(*, goal, plan_json, steps_summary, trigger, llm, registry, model=None):
        return planner_svc.RevisionSuggestion(
            kind="append_step",
            new_tail=[{"title": "换一种查询方式", "tool": "list_drones",
                       "args": {}, "why": "重试"}],
            reason="第一步失败，改用只读工具兜底",
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "reflect", fake_reflect)

    tok, _, _ = await _mkuser()
    # Manually craft a chain in "failed-ish" state via manual create
    r = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "查看甘孜机队",
            "plan": [{"title": "看一眼", "tool": "list_drones", "args": {}}],
        },
    )
    cid = r.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/reflect", headers=_h(tok),
        json={"trigger": "user_reflect", "apply": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"]["kind"] == "append_step"
    assert body["applied"] is not None
    assert body["applied"]["kind"] == "append_step"

    # Chain now has 2 steps
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    assert len(detail["chain"]["plan_json"]) == 2
    assert detail["revisions"][0]["kind"] == "append_step"


# ------------------------------------------------------------------
# Cross-org isolation
# ------------------------------------------------------------------
async def test_e2_cross_org_isolation(client, monkeypatch) -> None:
    """Approvals + chains must NOT leak between orgs."""
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_plan(*, goal, registry, llm, model=None, extra_hint=None):
        return planner_svc.PlanResult(
            subtasks=[
                {"title": "s", "tool": "create_mission",
                 "args": {"name": "x", "waypoints": []}, "why": ""},
            ],
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "plan", fake_plan)

    tok_a, _, org_a = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains/auto",
        headers=_h(tok_a), json={"goal": "org-A"},
    )
    cid_a = r.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid_a}/advance", headers=_h(tok_a),
    )

    # Different org's admin should NOT see A's pending approvals
    admin_b_tok, _, _ = await _mkuser("admin")
    r = await client.get(
        "/api/v1/copilot/task-chains/approvals/pending",
        headers=_h(admin_b_tok),
    )
    assert r.json()["items"] == []

    # Cannot fetch chain across org
    r = await client.get(
        f"/api/v1/copilot/task-chains/{cid_a}",
        headers=_h(admin_b_tok),
    )
    assert r.status_code == 404
