"""Service layer for Copilot workflow schedules · T12.1 (v2.1 E2.2).

Business rules:
  * A schedule belongs to one org and one workflow. Workflow must
    exist + belong to the same org + not be soft-deleted.
  * ``cron_expr`` must parse with croniter (raises ValueError on
    invalid input). No 6/7-field second-precision expressions — the
    scheduler only guarantees minute resolution.
  * Inputs are stored as JSONB; empty dict is fine. NOT re-validated
    against workflow inputs schema at create time — inputs are only
    checked at execution.
  * ``next_fire_at`` is computed at INSERT/UPDATE from cron_expr +
    now(UTC). Scheduler daemon (T12.2) will re-compute after each fire.
  * Disabling a schedule (``enabled=False``) sets next_fire_at=NULL so
    it drops out of the scheduler hot-path index.

Nothing here actually EXECUTES a workflow — that's the scheduler
daemon's job, and it can call ``compute_next_fire`` on its own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_workflow import CopilotWorkflow
from app.models.copilot_workflow_schedule import CopilotWorkflowSchedule


class ScheduleError(ValueError):
    """Semantic-level failure at create/update time."""


def compute_next_fire(
    cron_expr: str,
    base: datetime | None = None,
) -> datetime:
    """Return the next fire time (>= ``base``) for ``cron_expr``.

    Raises :class:`ScheduleError` on invalid cron.
    """
    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    try:
        it = croniter(cron_expr, base)
    except Exception as exc:  # croniter raises many things
        raise ScheduleError(f"invalid cron_expr: {cron_expr!r} — {exc}") from exc
    nxt = it.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt


async def _assert_workflow_in_org(
    db: AsyncSession,
    workflow_id: UUID,
    org_id: UUID,
) -> CopilotWorkflow:
    """Return the workflow if it exists in ``org_id`` and is not soft-deleted."""
    q = select(CopilotWorkflow).where(
        CopilotWorkflow.id == workflow_id,
        CopilotWorkflow.org_id == org_id,
        CopilotWorkflow.deleted_at.is_(None),
    )
    wf = (await db.execute(q)).scalar_one_or_none()
    if wf is None:
        raise ScheduleError("workflow not found in this org")
    return wf


async def create_schedule(
    db: AsyncSession,
    *,
    org_id: UUID,
    workflow_id: UUID,
    cron_expr: str,
    inputs: dict,
    created_by: UUID | None,
    enabled: bool = True,
) -> CopilotWorkflowSchedule:
    await _assert_workflow_in_org(db, workflow_id, org_id)
    next_fire = compute_next_fire(cron_expr) if enabled else None

    row = CopilotWorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        cron_expr=cron_expr,
        inputs_json=inputs or {},
        enabled=enabled,
        created_by=created_by,
        next_fire_at=next_fire,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_schedules(
    db: AsyncSession,
    *,
    org_id: UUID,
    workflow_id: UUID | None = None,
    limit: int = 100,
) -> list[CopilotWorkflowSchedule]:
    q = (
        select(CopilotWorkflowSchedule)
        .where(CopilotWorkflowSchedule.org_id == org_id)
        .order_by(CopilotWorkflowSchedule.created_at.desc())
        .limit(limit)
    )
    if workflow_id is not None:
        q = q.where(CopilotWorkflowSchedule.workflow_id == workflow_id)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def get_schedule(
    db: AsyncSession,
    *,
    org_id: UUID,
    schedule_id: UUID,
) -> CopilotWorkflowSchedule | None:
    q = select(CopilotWorkflowSchedule).where(
        CopilotWorkflowSchedule.id == schedule_id,
        CopilotWorkflowSchedule.org_id == org_id,
    )
    return (await db.execute(q)).scalar_one_or_none()


async def update_schedule(
    db: AsyncSession,
    *,
    org_id: UUID,
    schedule_id: UUID,
    cron_expr: str | None = None,
    inputs: dict | None = None,
    enabled: bool | None = None,
) -> CopilotWorkflowSchedule:
    row = await get_schedule(db, org_id=org_id, schedule_id=schedule_id)
    if row is None:
        raise ScheduleError("schedule not found")

    if cron_expr is not None:
        row.cron_expr = cron_expr
    if inputs is not None:
        row.inputs_json = inputs
    if enabled is not None:
        row.enabled = enabled

    # Recompute next_fire_at based on final state.
    if row.enabled:
        row.next_fire_at = compute_next_fire(row.cron_expr)
    else:
        row.next_fire_at = None

    await db.commit()
    await db.refresh(row)
    return row


async def delete_schedule(
    db: AsyncSession,
    *,
    org_id: UUID,
    schedule_id: UUID,
) -> bool:
    row = await get_schedule(db, org_id=org_id, schedule_id=schedule_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
