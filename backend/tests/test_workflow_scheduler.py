"""T12.2 · Scheduler daemon — tick loop, claim race, execution + audit.

Frozen-clock tests. The scheduler polls a real Postgres table, so we
drive it with a synthetic ``now`` and inspect the row updates rather
than sleeping.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_run import CopilotWorkflowRun
from app.models.copilot_workflow_schedule import CopilotWorkflowSchedule
from app.models.user import User
from app.services.auth import hash_password
from app.services.workflow_scheduler import _claim, tick_once
from app.services.workflow_schedules import create_schedule

pytestmark = pytest.mark.asyncio


# =========================================================== fixtures ===


async def _mkuser() -> tuple[UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"sd+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return uid, org


async def _mkworkflow(
    org: UUID, uid: UUID, dsl: str | None = None,
) -> UUID:
    wf_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotWorkflow(
            id=wf_id, org_id=org, owner_user_id=uid,
            name="sch-wf", description="",
            dsl_yaml=dsl or (
                'version: "0.1"\n'
                'name: sch-wf\n'
                'steps:\n'
                '  - id: a\n'
                '    tool: list_drones\n'
                '    args: {}\n'
            ),
            version=1,
        ))
        await s.commit()
    return wf_id


# ================================================================ tests ===


async def test_tick_fires_due_schedule(client) -> None:
    """Basic happy path: a schedule whose next_fire_at is in the past
    should fire on the next tick, produce a run row, and advance."""
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
        )
        original_next = sched.next_fire_at

    # Force clock past next_fire_at.
    fire_time = original_next + timedelta(minutes=1)

    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        assert fired == 1

    # Schedule advanced.
    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        assert row.last_fire_at == fire_time
        assert row.last_fire_status == "ok"
        assert row.last_fire_run_id is not None
        assert row.next_fire_at > fire_time  # cron rolled forward

    # Audit run persisted.
    async with S() as db:
        runs = (await db.execute(
            select(CopilotWorkflowRun).where(
                CopilotWorkflowRun.org_id == org,
            )
        )).scalars().all()
        assert len(runs) == 1
        assert runs[0].trace_json.get("scheduled") is True
        assert runs[0].trace_json.get("schedule_id") == str(sched.id)


async def test_tick_skips_disabled(client) -> None:
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
            enabled=False,
        )
        assert sched.next_fire_at is None

    # Force a "very late" clock.
    async with S() as db:
        fired = await tick_once(
            db, now=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        assert fired == 0


async def test_tick_skips_future_schedule(client) -> None:
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
        )
        original_next = sched.next_fire_at

    # Clock is BEFORE next fire.
    fire_time = original_next - timedelta(minutes=5)

    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        assert fired == 0

    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        assert row.last_fire_at is None
        # next_fire_at unchanged
        assert row.next_fire_at == original_next


async def test_claim_race_only_one_worker_wins(client) -> None:
    """The claim UPDATE is idempotent under race: run it twice with
    the same observed next_fire_at, only the first advances the row.

    Two workers each hold their own snapshot of the schedule (same
    observed ``next_fire_at``). After A commits, B's UPDATE ... WHERE
    next_fire_at = <A's_observed_value> matches 0 rows, so B returns
    False."""
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
        )

    new_time = datetime(2030, 1, 1, tzinfo=timezone.utc)

    # Worker A claims.
    async with S() as db_a:
        row_a = (await db_a.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        won_a = await _claim(db_a, row_a, new_next_fire=new_time)

    # Worker B sees stale snapshot (same next_fire_at as A did) —
    # simulate by using the original `sched` object which still holds
    # the pre-A next_fire_at value.
    async with S() as db_b:
        won_b = await _claim(db_b, sched, new_next_fire=new_time)

    assert won_a is True
    assert won_b is False


async def test_bad_cron_disables_schedule(client) -> None:
    """A schedule with a cron_expr that becomes invalid (e.g. after a
    manual DB tweak, or a future upgrade) shouldn't burn CPU forever.
    The scheduler must disable it after the first tick."""
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
        )
        original_next = sched.next_fire_at

    # Corrupt cron_expr in place (bypass service validation).
    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        row.cron_expr = "totally invalid"
        await db.commit()

    fire_time = original_next + timedelta(minutes=1)
    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        # Row was due but we couldn't compute next_fire → 0 fires.
        assert fired == 0

    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        assert row.enabled is False
        assert row.next_fire_at is None


async def test_deleted_workflow_records_failure(client) -> None:
    """Soft-delete the workflow between schedule creation and fire —
    the tick should record a synthetic failure run and advance the
    schedule (rather than crash-loop)."""
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        sched = await create_schedule(
            db, org_id=org, workflow_id=wf,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid,
        )
        original_next = sched.next_fire_at

    # Soft-delete workflow.
    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflow).where(CopilotWorkflow.id == wf)
        )).scalar_one()
        row.deleted_at = datetime.now(timezone.utc)
        await db.commit()

    fire_time = original_next + timedelta(minutes=1)
    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        assert fired == 1  # still counts as "processed"

    async with S() as db:
        row = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.id == sched.id,
            )
        )).scalar_one()
        assert row.last_fire_status == "failed"
        # No audit row because we couldn't load wf — that's the
        # trade-off.
        assert row.last_fire_run_id is None


async def test_multiple_due_schedules_all_fire(client) -> None:
    uid, org = await _mkuser()
    wf = await _mkworkflow(org, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        for _ in range(3):
            await create_schedule(
                db, org_id=org, workflow_id=wf,
                cron_expr="0 9 * * *",
                inputs={}, created_by=uid,
            )

    # Force clock way past any next_fire_at.
    fire_time = datetime(2030, 1, 1, 9, 30, tzinfo=timezone.utc)

    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        assert fired == 3

    async with S() as db:
        rows = (await db.execute(
            select(CopilotWorkflowSchedule).where(
                CopilotWorkflowSchedule.org_id == org,
            )
        )).scalars().all()
        assert all(r.last_fire_status == "ok" for r in rows)


async def test_org_isolation_scheduler_sees_all_orgs(client) -> None:
    """Scheduler is org-blind (system-level), but each executed run
    correctly carries its schedule's org_id — no cross-org leakage
    in the resulting audit row."""
    uid_a, org_a = await _mkuser()
    uid_b, org_b = await _mkuser()
    wf_a = await _mkworkflow(org_a, uid_a)
    wf_b = await _mkworkflow(org_b, uid_b)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        await create_schedule(
            db, org_id=org_a, workflow_id=wf_a,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid_a,
        )
        await create_schedule(
            db, org_id=org_b, workflow_id=wf_b,
            cron_expr="0 9 * * *",
            inputs={}, created_by=uid_b,
        )

    fire_time = datetime(2030, 1, 1, 9, 30, tzinfo=timezone.utc)
    async with S() as db:
        fired = await tick_once(db, now=fire_time)
        assert fired == 2

    async with S() as db:
        runs_a = (await db.execute(
            select(CopilotWorkflowRun).where(
                CopilotWorkflowRun.org_id == org_a,
            )
        )).scalars().all()
        runs_b = (await db.execute(
            select(CopilotWorkflowRun).where(
                CopilotWorkflowRun.org_id == org_b,
            )
        )).scalars().all()
        assert len(runs_a) == 1
        assert len(runs_b) == 1
        # Verify no cross-contamination.
        assert runs_a[0].workflow_id == wf_a
        assert runs_b[0].workflow_id == wf_b
