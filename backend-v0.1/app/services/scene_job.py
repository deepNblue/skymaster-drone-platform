"""Scene job queue service — v2.1 T2.3.

Business logic for enqueue / claim / heartbeat / complete / fail / cancel.
Route layer stays thin.

Concurrency model
-----------------
Single-source-of-truth is the Postgres row. Workers claim a row via
``UPDATE ... WHERE status='queued' ...`` with row-level locking (via
SQLAlchemy's ``with_for_update(skip_locked=True)``). Under load with
Postgres 12+, this is safe and lock-free between workers.

For SQLite in tests we fall back to a naive claim (SQLite has no
``SELECT FOR UPDATE SKIP LOCKED``) — the test suite is single-worker so
it's fine.

Lease expiry
------------
Every claim sets ``lease_expires_at = now + lease_ttl``. Workers must
call ``heartbeat`` before expiry to extend. A GC pass (``reclaim_stale``)
runs in a background loop and moves expired leases back to ``queued``
with ``attempts += 1``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene_job import JOB_KINDS, JOB_STATUSES, MAX_ATTEMPTS, SceneJob


class JobError(Exception):
    pass


DEFAULT_LEASE_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


@dataclass
class EnqueueParams:
    scene_id: UUID
    kind: str
    priority: int = 0


async def enqueue(db: AsyncSession, params: EnqueueParams) -> SceneJob:
    if params.kind not in JOB_KINDS:
        raise JobError(f"unknown kind {params.kind!r}")
    # Deduplicate: refuse to enqueue if there's already an active job
    # of the same kind for this scene.
    existing = (
        await db.execute(select(SceneJob).where(
            SceneJob.scene_id == params.scene_id,
            SceneJob.kind == params.kind,
            SceneJob.status.in_(["queued", "leased", "running"]),
        ))
    ).scalar_one_or_none()
    if existing is not None:
        raise JobError(f"duplicate active job of kind {params.kind!r} for scene {params.scene_id}")

    job = SceneJob(
        scene_id=params.scene_id,
        kind=params.kind,
        priority=params.priority,
        status="queued",
    )
    db.add(job)
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# Claim (worker side)
# ---------------------------------------------------------------------------


async def claim_next(
    db: AsyncSession, worker_id: str, kinds: Optional[list[str]] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Optional[SceneJob]:
    """Atomically claim the next queued job matching ``kinds``.

    Returns the claimed job, or None if the queue is empty.
    """
    if not worker_id:
        raise JobError("worker_id required")
    kinds = kinds or list(JOB_KINDS)
    for k in kinds:
        if k not in JOB_KINDS:
            raise JobError(f"unknown kind {k!r}")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=lease_seconds)

    # First: promote any expired leases back to queued
    await reclaim_stale(db)

    # Pick highest priority, then oldest
    q = (
        select(SceneJob)
        .where(and_(SceneJob.status == "queued", SceneJob.kind.in_(kinds)))
        .order_by(SceneJob.priority.desc(), SceneJob.created_at.asc())
        .limit(1)
    )
    # SKIP LOCKED works on Postgres 9.5+; SQLite falls back gracefully
    dialect = db.bind.dialect.name if db.bind else ""
    if dialect == "postgresql":
        q = q.with_for_update(skip_locked=True)
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        return None

    row.status = "leased"
    row.worker_id = worker_id
    row.leased_at = now
    row.lease_expires_at = exp
    row.attempts = (row.attempts or 0) + 1
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def heartbeat(
    db: AsyncSession, job_id: UUID, worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    running: bool = True,
) -> SceneJob:
    job = (
        await db.execute(select(SceneJob).where(SceneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise JobError("job not found")
    if job.worker_id != worker_id:
        raise JobError(f"lease is held by another worker {job.worker_id!r}")
    if job.status not in ("leased", "running"):
        raise JobError(f"cannot heartbeat job in status {job.status!r}")

    now = datetime.now(timezone.utc)
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if running and job.status == "leased":
        job.status = "running"
        job.started_at = now
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# Complete / fail / cancel
# ---------------------------------------------------------------------------


@dataclass
class CompleteParams:
    n_points: Optional[int] = None
    n_gaussians: Optional[int] = None
    psnr: Optional[float] = None


async def complete(
    db: AsyncSession, job_id: UUID, worker_id: str,
    result: Optional[CompleteParams] = None,
) -> SceneJob:
    job = (
        await db.execute(select(SceneJob).where(SceneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise JobError("job not found")
    if job.worker_id != worker_id:
        raise JobError(f"lease held by another worker {job.worker_id!r}")
    if job.status in ("succeeded", "failed", "dead", "canceled"):
        raise JobError(f"job already terminal ({job.status})")

    job.status = "succeeded"
    job.finished_at = datetime.now(timezone.utc)
    job.lease_expires_at = None
    if result:
        job.result_n_points = result.n_points
        job.result_n_gaussians = result.n_gaussians
        job.result_psnr = result.psnr
    await db.flush()
    return job


async def fail(
    db: AsyncSession, job_id: UUID, worker_id: str, error: str,
) -> SceneJob:
    job = (
        await db.execute(select(SceneJob).where(SceneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise JobError("job not found")
    if job.worker_id != worker_id:
        raise JobError(f"lease held by another worker {job.worker_id!r}")
    if job.status in ("succeeded", "failed", "dead", "canceled"):
        raise JobError(f"job already terminal ({job.status})")

    job.last_error = error[:2000] if error else "unknown"
    job.finished_at = datetime.now(timezone.utc)
    job.lease_expires_at = None

    if job.attempts >= MAX_ATTEMPTS:
        job.status = "dead"
    else:
        # Requeue for retry — but clear the lease so another worker can pick it up
        job.status = "queued"
        job.worker_id = None
        job.leased_at = None
    await db.flush()
    return job


async def cancel(db: AsyncSession, job_id: UUID) -> SceneJob:
    job = (
        await db.execute(select(SceneJob).where(SceneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise JobError("job not found")
    if job.status in ("succeeded", "failed", "dead", "canceled"):
        raise JobError(f"job already terminal ({job.status})")
    job.status = "canceled"
    job.finished_at = datetime.now(timezone.utc)
    job.lease_expires_at = None
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


async def reclaim_stale(db: AsyncSession) -> int:
    """Move any leased/running job with expired lease back to queued.

    Returns the number of jobs reclaimed. Called opportunistically at the
    top of ``claim_next``, and can also be invoked periodically by a
    janitor loop.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(SceneJob)
        .where(
            SceneJob.status.in_(["leased", "running"]),
            SceneJob.lease_expires_at.is_not(None),
            SceneJob.lease_expires_at < now,
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    n = 0
    for r in rows:
        r.last_error = (r.last_error or "") + f"\n[lease expired at {r.lease_expires_at.isoformat()}]"
        if r.attempts >= MAX_ATTEMPTS:
            r.status = "dead"
        else:
            r.status = "queued"
            r.worker_id = None
            r.leased_at = None
            r.lease_expires_at = None
        n += 1
    if n:
        await db.flush()
    return n


# ---------------------------------------------------------------------------
# Queue stats (for /admin dashboard)
# ---------------------------------------------------------------------------


from sqlalchemy import func as _f  # noqa: E402


async def queue_stats(db: AsyncSession) -> dict:
    stmt = (
        select(SceneJob.kind, SceneJob.status, _f.count(SceneJob.id))
        .group_by(SceneJob.kind, SceneJob.status)
    )
    rows = (await db.execute(stmt)).all()
    counts: dict[str, dict[str, int]] = {}
    for kind, status, n in rows:
        counts.setdefault(kind, {})[status] = int(n)
    return {
        "by_kind": counts,
        "total": sum(sum(v.values()) for v in counts.values()),
    }
