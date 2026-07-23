"""E2.4 · Task Chain 测试."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"tc+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


# ============ Create + validate ============

async def test_create_happy(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "查看无人机状态并列出巡检任务",
            "plan": [
                {"title": "列出无人机", "tool": "list_drones", "args": {}},
                {"title": "列出任务", "tool": "list_missions", "args": {}},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["current_index"] == 0
    assert len(body["plan_json"]) == 2


async def test_create_unknown_tool_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "bad",
            "plan": [{"title": "x", "tool": "nonexistent_tool", "args": {}}],
        },
    )
    assert r.status_code == 400
    assert "unknown tool" in r.text


async def test_create_empty_plan_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={"goal": "x", "plan": []},
    )
    # pydantic min_length rejects at 422
    assert r.status_code in (400, 422)


# ============ Advance / Run ============

async def test_advance_single_step(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "one",
            "plan": [{"title": "s1", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["step"]["status"] == "succeeded"
    assert body["chain"]["status"] == "completed"


async def test_run_to_end(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "multi",
            "plan": [
                {"title": "d", "tool": "list_drones", "args": {}},
                {"title": "m", "tool": "list_missions", "args": {}},
            ],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/run", headers=_h(tok),
    )
    body = r.json()
    assert body["chain"]["status"] == "completed"
    assert body["chain"]["current_index"] == 2
    assert len(body["steps"]) == 2
    assert all(s["status"] == "succeeded" for s in body["steps"])


async def test_run_stops_on_failure(client) -> None:
    tok, _, _ = await _mkuser()
    # Use invalid mission_id args that pydantic ArgSchema will reject
    # → registry.call will raise ValidationError → step.status=failed
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "fail-fast",
            "plan": [
                {
                    "title": "bad", "tool": "get_mission_detail",
                    "args": {},  # missing required mission_id
                },
                {"title": "unreached", "tool": "list_drones", "args": {}},
            ],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/run", headers=_h(tok),
    )
    body = r.json()
    assert body["chain"]["status"] == "failed"
    assert body["chain"]["current_index"] == 0
    assert len(body["steps"]) == 1
    assert body["steps"][0]["status"] == "failed"


async def test_advance_past_end_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "one",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    await client.post(f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok))
    r = await client.post(f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok))
    assert r.status_code == 400
    assert "completed" in r.text or "finished" in r.text


# ============ Get / List ============

async def test_get_returns_chain_steps_revisions(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "peek",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    await client.post(f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok))
    r = await client.get(f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok))
    body = r.json()
    assert body["chain"]["status"] == "completed"
    assert len(body["steps"]) == 1
    assert body["revisions"] == []


async def test_get_other_org_denied(client) -> None:
    tok_a, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok_a),
        json={
            "goal": "isolation",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    tok_b, _, _ = await _mkuser()
    r = await client.get(f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok_b))
    assert r.status_code == 404


async def test_list_filters(client) -> None:
    tok, _, _ = await _mkuser()
    for i in range(3):
        await client.post(
            "/api/v1/copilot/task-chains", headers=_h(tok),
            json={
                "goal": f"g{i}",
                "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
            },
        )
    r = await client.get(
        "/api/v1/copilot/task-chains?status=draft", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3


# ============ Revise ============

async def test_revise_append_step(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "revise",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/revise", headers=_h(tok),
        json={
            "kind": "append_step",
            "new_tail": [{"title": "s2", "tool": "list_missions", "args": {}}],
            "reason": "need missions too",
        },
    )
    assert r.status_code == 200
    detail = await client.get(f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok))
    assert len(detail.json()["chain"]["plan_json"]) == 2
    assert len(detail.json()["revisions"]) == 1


async def test_revise_replace_remaining_keeps_history(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "replace",
            "plan": [
                {"title": "s1", "tool": "list_drones", "args": {}},
                {"title": "s2 (will be replaced)", "tool": "list_missions", "args": {}},
            ],
        },
    )
    cid = c.json()["id"]
    # Advance step 1 first, so index=1 remains in tail
    await client.post(f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok))

    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/revise", headers=_h(tok),
        json={
            "kind": "replace_remaining",
            "new_tail": [
                {"title": "new-s2", "tool": "list_drones", "args": {}},
            ],
            "reason": "changed mind",
        },
    )
    assert r.status_code == 200
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    plan = detail["chain"]["plan_json"]
    assert len(plan) == 2
    # First one is the executed original
    assert plan[0]["title"] == "s1"
    assert plan[1]["title"] == "new-s2"


async def test_revise_abort(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "abort-me",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/revise", headers=_h(tok),
        json={"kind": "abort", "reason": "no longer needed"},
    )
    assert r.status_code == 200
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    assert detail["chain"]["status"] == "cancelled"


async def test_revise_completed_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "done",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    await client.post(f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok))
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/revise", headers=_h(tok),
        json={
            "kind": "append_step",
            "new_tail": [{"title": "late", "tool": "list_drones", "args": {}}],
            "reason": "too late",
        },
    )
    assert r.status_code == 400
    assert "completed" in r.text


# ============ Cancel ============

async def test_cancel_chain(client) -> None:
    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "cancel",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/cancel", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


async def test_cancel_by_other_user_rejected(client) -> None:
    tok_a, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok_a),
        json={
            "goal": "mine",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    tok_b, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/cancel", headers=_h(tok_b),
    )
    # Different org → 400 not accessible (get_chain fails first)
    assert r.status_code == 400


# ============ LLM-driven plan / auto / reflect endpoints ============

async def test_plan_endpoint_via_monkey(client, monkeypatch) -> None:
    """/plan returns LLM-drafted plan without persisting."""
    import json as _json

    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_plan(*, goal, llm, registry, model=None):
        return planner_svc.PlanResult(
            subtasks=[{
                "title": "auto-generated",
                "tool": "list_drones",
                "args": {},
                "why": "start with fleet snapshot",
            }],
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "plan", fake_plan)

    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains/plan", headers=_h(tok),
        json={"goal": "auto-plan me"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"][0]["tool"] == "list_drones"

    # /plan should NOT create a chain
    listing = await client.get("/api/v1/copilot/task-chains", headers=_h(tok))
    assert listing.json()["items"] == []


async def test_auto_endpoint_creates_chain(client, monkeypatch) -> None:
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_plan(*, goal, llm, registry, model=None):
        return planner_svc.PlanResult(
            subtasks=[{
                "title": "one", "tool": "list_drones", "args": {}, "why": "y",
            }],
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "plan", fake_plan)

    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/task-chains/auto", headers=_h(tok),
        json={"goal": "auto create me"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "draft"

    listing = await client.get("/api/v1/copilot/task-chains", headers=_h(tok))
    assert len(listing.json()["items"]) == 1


async def test_reflect_endpoint_applies_suggestion(client, monkeypatch) -> None:
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_reflect(*, goal, plan_json, steps_summary, trigger, llm, registry, model=None):
        return planner_svc.RevisionSuggestion(
            kind="append_step",
            new_tail=[{
                "title": "extra", "tool": "list_missions",
                "args": {}, "why": "补一步",
            }],
            reason="需要补一步任务列表",
            raw_response="",
        )
    monkeypatch.setattr(planner_svc, "reflect", fake_reflect)

    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "reflect me",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/reflect", headers=_h(tok),
        json={"trigger": "user_reflect", "apply": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"]["kind"] == "append_step"
    assert body["applied"]["kind"] == "append_step"

    detail = await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )
    plan = detail.json()["chain"]["plan_json"]
    assert len(plan) == 2  # original + appended
    assert plan[1]["title"] == "extra"


async def test_reflect_endpoint_no_apply(client, monkeypatch) -> None:
    from app.services import copilot_task_chain_planner as planner_svc

    async def fake_reflect(*, goal, plan_json, steps_summary, trigger, llm, registry, model=None):
        return planner_svc.RevisionSuggestion(
            kind="abort", new_tail=None, reason="太危险了", raw_response="",
        )
    monkeypatch.setattr(planner_svc, "reflect", fake_reflect)

    tok, _, _ = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "keep me alive",
            "plan": [{"title": "s", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/reflect", headers=_h(tok),
        json={"trigger": "off_track", "apply": False},
    )
    body = r.json()
    assert body["suggestion"]["kind"] == "abort"
    assert "applied" not in body

    # chain should still be draft (not cancelled)
    detail = await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )
    assert detail.json()["chain"]["status"] == "draft"


# ============ E2.5 Approval integration ============

async def _mkuser_role(role: str) -> tuple[str, UUID, UUID]:
    """Create a user with a specific role in a fresh org."""
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"tc+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role=role), uid, org


async def _mkuser_in_org(role: str, org_id: UUID) -> tuple[str, UUID]:
    """Create another user in the SAME org (for approver tests)."""
    uid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"tc+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def test_sensitive_tool_pauses_chain(client) -> None:
    """`create_mission` is sensitive → chain must pause & create approval."""
    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "sensitive path",
            "plan": [{
                "title": "危险步骤",
                "tool": "create_mission",
                # minimal args — resolution may fail but only after approval
                "args": {"name": "test-m", "waypoints": []},
            }],
        },
    )
    assert c.status_code == 200
    cid = c.json()["id"]

    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    body = r.json()
    assert body["step"]["status"] == "paused"
    assert body["chain"]["status"] == "paused"

    # An approval row should exist
    ap = await client.get(
        f"/api/v1/copilot/task-chains/{cid}/approvals", headers=_h(tok),
    )
    items = ap.json()["items"]
    assert len(items) == 1
    assert items[0]["tool_name"] == "create_mission"
    assert items[0]["status"] == "pending"
    assert items[0]["permission"] == "sensitive"


async def test_pending_approvals_scoped_by_org(client) -> None:
    """Pending listing only returns approvals in caller's org."""
    tok_a, _, org_a = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok_a),
        json={
            "goal": "org A",
            "plan": [{
                "title": "s", "tool": "create_mission",
                "args": {"name": "x", "waypoints": []},
            }],
        },
    )
    cid = c.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok_a),
    )

    tok_b, _, _ = await _mkuser()  # different org
    r = await client.get(
        "/api/v1/copilot/task-chains/approvals/pending", headers=_h(tok_b),
    )
    assert r.status_code == 200
    assert r.json()["items"] == []

    # Owner's org sees it
    r2 = await client.get(
        "/api/v1/copilot/task-chains/approvals/pending", headers=_h(tok_a),
    )
    assert len(r2.json()["items"]) == 1


async def test_approve_rejects_non_privileged_user(client) -> None:
    tok, _, _ = await _mkuser()  # role=user
    # Fake approval id — call should 403 before hitting the DB
    r = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{uuid4()}/decide",
        headers=_h(tok),
        json={"decision": "approved", "reason": "why not"},
    )
    assert r.status_code == 403


async def test_approve_rejected_flow(client) -> None:
    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "reject me",
            "plan": [{
                "title": "s", "tool": "create_mission",
                "args": {"name": "x", "waypoints": []},
            }],
        },
    )
    cid = c.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    ap = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}/approvals", headers=_h(tok),
    )).json()["items"][0]

    admin_tok, _ = await _mkuser_in_org("admin", org)
    r = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{ap['id']}/decide",
        headers=_h(admin_tok),
        json={"decision": "rejected", "reason": "太危险了"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval"]["status"] == "rejected"

    # Chain should be failed
    detail = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}", headers=_h(tok),
    )).json()
    assert detail["chain"]["status"] == "failed"
    assert "rejected" in detail["chain"]["error"]


async def test_approve_approved_resume_hits_tool_error(client) -> None:
    """After approval, the paused step is re-created and re-run.

    With minimal fake args, `create_mission` will fail at tool level — but
    the important thing is: the step transitions past `paused`, and the
    approval row's status becomes `approved`.
    """
    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "approve me",
            "plan": [{
                "title": "s", "tool": "create_mission",
                "args": {"name": "x", "waypoints": []},
            }],
        },
    )
    cid = c.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    ap = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}/approvals", headers=_h(tok),
    )).json()["items"][0]

    admin_tok, _ = await _mkuser_in_org("admin", org)
    r = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{ap['id']}/decide?resume=true",
        headers=_h(admin_tok),
        json={"decision": "approved", "reason": "ok, tested"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval"]["status"] == "approved"
    assert body["approval"]["approver_id"] is not None
    # Either resumed_step present (if resume ran) or resume_error field
    assert "resumed_step" in body or "resume_error" in body


async def test_double_decide_rejected(client) -> None:
    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "twice",
            "plan": [{
                "title": "s", "tool": "create_mission",
                "args": {"name": "x", "waypoints": []},
            }],
        },
    )
    cid = c.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    ap = (await client.get(
        f"/api/v1/copilot/task-chains/{cid}/approvals", headers=_h(tok),
    )).json()["items"][0]

    admin_tok, _ = await _mkuser_in_org("admin", org)
    r1 = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{ap['id']}/decide?resume=false",
        headers=_h(admin_tok),
        json={"decision": "rejected", "reason": "no"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/copilot/task-chains/approvals/{ap['id']}/decide?resume=false",
        headers=_h(admin_tok),
        json={"decision": "approved", "reason": "flip flop"},
    )
    assert r2.status_code == 400


# ============ E2.6 Task-history writeback ============

async def test_writeback_on_completion(client) -> None:
    """When a chain runs to completion, a task_history memory is created."""
    from sqlalchemy import select
    from app.models.copilot_memory import CopilotMemory

    tok, uid, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "count drones",
            "plan": [{"title": "list", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]

    # advance once → completes (single-step plan)
    r = await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    assert r.json()["chain"]["status"] == "completed"

    # Verify memory row exists
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
    assert "count drones" in mem.content
    assert "completed" in mem.content
    assert mem.meta and mem.meta.get("chain_id") == cid
    assert mem.weight == 60


async def test_writeback_on_cancel(client) -> None:
    from sqlalchemy import select
    from app.models.copilot_memory import CopilotMemory

    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "cancel me",
            "plan": [{"title": "list", "tool": "list_drones", "args": {}}],
        },
    )
    cid = c.json()["id"]
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/cancel", headers=_h(tok),
    )

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
    # cancelled status is a terminal state but writeback uses `cancelled`
    # (weight=45 since != completed)
    assert mem.weight == 45
    assert "cancelled" in mem.content


async def test_writeback_upsert_no_duplicate(client) -> None:
    """Running/cancelling the same chain must not create duplicate memories."""
    from sqlalchemy import select, func
    from app.models.copilot_memory import CopilotMemory

    tok, _, org = await _mkuser()
    c = await client.post(
        "/api/v1/copilot/task-chains", headers=_h(tok),
        json={
            "goal": "dup guard",
            "plan": [
                {"title": "l1", "tool": "list_drones", "args": {}},
                {"title": "l2", "tool": "list_drones", "args": {}},
            ],
        },
    )
    cid = c.json()["id"]

    # First advance → 1/2, no writeback yet
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )
    # Second advance → completed → 1 writeback
    await client.post(
        f"/api/v1/copilot/task-chains/{cid}/advance", headers=_h(tok),
    )

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        res = await s.execute(
            select(func.count()).select_from(CopilotMemory).where(
                CopilotMemory.key == f"task_chain:{cid}",
            )
        )
        count = res.scalar_one()
    assert count == 1
