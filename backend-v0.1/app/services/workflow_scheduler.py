"""Copilot workflow scheduler daemon · T12.2 (v2.1 E2.2).

An asyncio background task that fires schedules whose ``next_fire_at``
has passed. Runs inside the FastAPI process (single-node deployment
model of v1.x/v2.0); when we scale horizontally we'll swap the
in-process ticker for a redis-lock-based lease.

Reuses the same execution path as manual /run — so sensitive-tool
approval, org isolation, and run audit all keep working unchanged.

Design notes
------------
* **Claim-then-execute pattern.** Before running a schedule we
  atomically advance ``next_fire_at`` to the *next* fire time. Any
  parallel worker will see the row already claimed and skip it. This
  is worst-case "at-most-one execution per fire window" — a run may
  be lost if the process crashes between claim and execution, but
  we prefer safe-under-crash to double-fire under race.
* **No SKIP LOCKED / advisory locks.** The claim UPDATE ... WHERE
  next_fire_at = <original> is the only mutex; if two workers pick
  the same row, only one WHERE clause matches and the other returns
  0 rows.
* **Testable via ``tick_once()``.** The async ``run_forever()`` loop
  just wraps ``tick_once`` + ``asyncio.sleep`` — tests inject a
  frozen clock and call the sync-style entry directly.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Callable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_run import CopilotWorkflowRun
from app.models.copilot_workflow_schedule import CopilotWorkflowSchedule
from app.services.tool_registry import ToolContext, build_default_registry
from app.services.workflow_dsl import (
    WorkflowError,
    parse_workflow,
    validate_workflow,
)
from app.services.workflow_executor import WorkflowExecutor
from app.services.workflow_schedules import compute_next_fire

log = logging.getLogger(__name__)


# Public knobs, tunable at deploy time.
TICK_INTERVAL_SECONDS: float = 30.0

#: Max schedules processed per tick. Prevents a large backlog from
#: monopolising the loop. Realistic tenants: <100 schedules, so this
#: is comfortable slack.
MAX_PER_TICK: int = 32


ClockFn = Callable[[], datetime]
"""Injectable clock for tests; returns aware UTC datetime."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------- #
# Core tick                                                            #
# ------------------------------------------------------------------- #


async def _fetch_due(
    db: AsyncSession, *, now: datetime, limit: int,
) -> list[CopilotWorkflowSchedule]:
    q = (
        select(CopilotWorkflowSchedule)
        .where(
            CopilotWorkflowSchedule.enabled.is_(True),
            CopilotWorkflowSchedule.next_fire_at.is_not(None),
            CopilotWorkflowSchedule.next_fire_at <= now,
        )
        .order_by(CopilotWorkflowSchedule.next_fire_at.asc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def _claim(
    db: AsyncSession,
    sched: CopilotWorkflowSchedule,
    *,
    new_next_fire: datetime,
) -> bool:
    """Atomically advance ``next_fire_at`` from the observed value to
    ``new_next_fire``. Returns True if we won the claim."""
    stmt = (
        update(CopilotWorkflowSchedule)
        .where(
            CopilotWorkflowSchedule.id == sched.id,
            CopilotWorkflowSchedule.next_fire_at == sched.next_fire_at,
        )
        .values(next_fire_at=new_next_fire)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount == 1


async def _load_workflow(
    db: AsyncSession, workflow_id: UUID, org_id: UUID,
) -> CopilotWorkflow | None:
    q = select(CopilotWorkflow).where(
        CopilotWorkflow.id == workflow_id,
        CopilotWorkflow.org_id == org_id,
        CopilotWorkflow.deleted_at.is_(None),
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _execute_and_record(
    db: AsyncSession, sched: CopilotWorkflowSchedule,
) -> tuple[str, UUID | None]:
    """Run the underlying workflow, persist a run row, return
    (status, run_id) so the caller can update the schedule."""
    wf = await _load_workflow(db, sched.workflow_id, sched.org_id)
    if wf is None:
        # Workflow was deleted between schedule creation and fire.
        # This should be rare because CASCADE deletes schedules with
        # their parent, but there's a window during soft-delete
        # (deleted_at set, row still present).
        return "failed", None

    try:
        doc = parse_workflow(wf.dsl_yaml)
        registry = build_default_registry()
        validate_workflow(doc, registry)
    except WorkflowError as exc:
        log.warning(
            "scheduler: workflow %s DSL invalid: %s", wf.id, exc,
        )
        # Record a failed synthetic run so users see WHY their
        # schedule stopped firing (rather than silently dying).
        return "failed", await _record_failure_run(
            db, sched=sched, wf=wf,
            error=f"scheduler validate: {exc}",
        )

    ctx = ToolContext(
        org_id=sched.org_id,
        # created_by may be None for org-owned schedules; that's fine —
        # tools inspect ctx.user_id only for user-scoped operations.
        user_id=sched.created_by,
    )

    try:
        run = await WorkflowExecutor(registry).run(
            doc, inputs=sched.inputs_json or {}, ctx=ctx,
        )
    except Exception as exc:  # noqa: BLE001 — executor may raise anything
        log.exception("scheduler: executor crashed on schedule %s", sched.id)
        return "failed", await _record_failure_run(
            db, sched=sched, wf=wf,
            error=f"scheduler executor: {exc!r}",
        )

    # Persist audit row (mirror /run path).
    run_id: UUID | None
    try:
        row = CopilotWorkflowRun(
            org_id=sched.org_id,
            user_id=sched.created_by,
            workflow_id=wf.id,
            workflow_name=run.workflow_name,
            status=run.status,
            duration_ms=run.duration_ms,
            error=run.error,
            trace_json={
                "scheduled": True,
                "schedule_id": str(sched.id),
                "workflow_name": run.workflow_name,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "steps": [
                    {
                        "id": s.id, "tool": s.tool, "status": s.status,
                        "resolved_args": s.resolved_args,
                        "result": s.result, "error": s.error,
                        "duration_ms": s.duration_ms,
                    }
                    for s in run.steps
                ],
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        run_id = row.id
    except Exception:  # noqa: BLE001
        log.exception("scheduler: audit persist failed")
        await db.rollback()
        run_id = None

    return run.status, run_id


async def _record_failure_run(
    db: AsyncSession,
    *,
    sched: CopilotWorkflowSchedule,
    wf: CopilotWorkflow,
    error: str,
) -> UUID | None:
    try:
        row = CopilotWorkflowRun(
            org_id=sched.org_id,
            user_id=sched.created_by,
            workflow_id=wf.id,
            workflow_name=wf.name,
            status="failed",
            duration_ms=0,
            error=error,
            trace_json={
                "scheduled": True,
                "schedule_id": str(sched.id),
                "error": error,
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id
    except Exception:  # noqa: BLE001
        log.exception("scheduler: failure audit persist failed")
        await db.rollback()
        return None


async def _finalize(
    db: AsyncSession,
    sched: CopilotWorkflowSchedule,
    *,
    fired_at: datetime,
    status: str,
    run_id: UUID | None,
) -> None:
    """Write last_fire_* fields. next_fire_at was already advanced in
    ``_claim`` so we only update observability columns here."""
    stmt = (
        update(CopilotWorkflowSchedule)
        .where(CopilotWorkflowSchedule.id == sched.id)
        .values(
            last_fire_at=fired_at,
            last_fire_status=status,
            last_fire_run_id=run_id,
        )
    )
    await db.execute(stmt)
    await db.commit()


async def tick_once(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = MAX_PER_TICK,
) -> int:
    """Fire every schedule whose ``next_fire_at <= now``.

    Returns the number of schedules successfully claimed and executed.
    Safe to call from a test suite with a frozen clock.
    """
    now = now or _utcnow()
    fired = 0

    due = await _fetch_due(db, now=now, limit=limit)
    for sched in due:
        try:
            new_next = compute_next_fire(sched.cron_expr, base=now)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "scheduler: bad cron on schedule %s: %s", sched.id, exc,
            )
            # Disable schedule to prevent tight-loop on bad cron.
            await db.execute(
                update(CopilotWorkflowSchedule)
                .where(CopilotWorkflowSchedule.id == sched.id)
                .values(enabled=False, next_fire_at=None)
            )
            await db.commit()
            continue

        won = await _claim(db, sched, new_next_fire=new_next)
        if not won:
            # Someone else claimed this fire window — skip.
            continue

        status, run_id = await _execute_and_record(db, sched)
        await _finalize(
            db, sched,
            fired_at=now, status=status, run_id=run_id,
        )
        fired += 1

    return fired


# ------------------------------------------------------------------- #
# Long-running loop (started from FastAPI lifespan)                    #
# ------------------------------------------------------------------- #


async def run_forever(
    session_factory: Callable[[], AsyncSession],
    *,
    interval_seconds: float = TICK_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Poll loop entry point.

    ``session_factory`` should return a new AsyncSession per tick so
    long-lived transactions don't accumulate. Stop by setting
    ``stop_event`` (used in tests and graceful shutdown).
    """
    stop_event = stop_event or asyncio.Event()
    log.info("scheduler: starting, interval=%.1fs", interval_seconds)

    while not stop_event.is_set():
        try:
            async with session_factory() as db:  # type: ignore[misc]
                await tick_once(db)
        except Exception:  # noqa: BLE001 — one bad tick shouldn't kill the loop
            log.exception("scheduler: tick failed")

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=interval_seconds,
            )
        except asyncio.TimeoutError:
            pass

    log.info("scheduler: stopped")


@asynccontextmanager
async def scheduler_lifespan(
    session_factory: Callable[[], AsyncSession],
    *,
    interval_seconds: float = TICK_INTERVAL_SECONDS,
    enabled: bool = True,
) -> AsyncIterator[None]:
    """FastAPI lifespan integration.

    Skips the background task when ``enabled=False`` — useful in tests
    that want to invoke ``tick_once`` directly without racing the
    background loop.
    """
    if not enabled:
        yield
        return

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_forever(
            session_factory,
            interval_seconds=interval_seconds,
            stop_event=stop,
        ),
        name="copilot-workflow-scheduler",
    )
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("scheduler: shutdown timeout, cancelling task")
            task.cancel()
