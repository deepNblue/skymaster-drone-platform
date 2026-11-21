"""T12.4 · Fire-now endpoint tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_run import CopilotWorkflowRun
from app.models.copilot_workflow_schedule import CopilotWorkflowSchedule
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.workflow_schedules import create_schedule

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"fn+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


async def _mkworkflow(org: UUID, uid: UUID) -> UUID:
    wf_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotWorkflow(
            id=wf_id, org_id=org, owner_user_id=uid,
            name="fn-wf", description="",
            dsl_yaml=(
                'version: "0.1"\nname: fn-wf\n'
                'steps:\n  - id: a\n    tool: list_drones\n    args: {}\n'
            ),
            version=1,
        ))
        await s.commit()
    return wf_id


async def _mkschedule(org: UUID, uid: UUID, wf: UUID, *, enabled=True):
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        return await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *", inputs={}, created_by=uid,
            enabled=enabled,
        )


async def test_fire_now_runs_immediately(client) -> None:
    tok, uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)
    sched = await _mkschedule(org, uid, wf)
    original_next = sched.next_fire_at

    r = await client.post(
        f"/api/v1/copilot/workflows/schedules/{sched.id}/fire-now",
        headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["run_id"] is not None

    # next_fire_at MUST NOT be touched by fire-now.
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        assert row.next_fire_at == original_next
        assert row.last_fire_status == "ok"
        assert row.last_fire_run_id is not None

    # Audit run is marked manual.
    async with S() as db:
        run = (await db.execute(
            select(CopilotWorkflowRun).where(
                CopilotWorkflowRun.id == UUID(body["run_id"]),
            )
        )).scalar_one()
        assert run.trace_json.get("scheduled") is True
        assert run.trace_json.get("fired_manually") is True
        assert run.trace_json.get("fired_by") == str(uid)


async def test_fire_now_works_even_when_disabled(client) -> None:
    """User asks for a one-shot regardless of scheduler state."""
    tok, uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)
    sched = await _mkschedule(org, uid, wf, enabled=False)

    r = await client.post(
        f"/api/v1/copilot/workflows/schedules/{sched.id}/fire-now",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_fire_now_missing_404(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/copilot/workflows/schedules/{uuid4()}/fire-now",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_fire_now_cross_org_404(client) -> None:
    tok_a, _, _ = await _mkuser()
    _, uid_b, org_b = await _mkuser()
    wf_b = await _mkworkflow(org_b, uid_b)
    sched_b = await _mkschedule(org_b, uid_b, wf_b)

    r = await client.post(
        f"/api/v1/copilot/workflows/schedules/{sched_b.id}/fire-now",
        headers=_h(tok_a),
    )
    assert r.status_code == 404  # not visible to org A
