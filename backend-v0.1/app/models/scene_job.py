"""Scene job queue tables — v2.1 T2.3.

Durable job records that back the ``QueueExecutor``. This is the piece
that lets the API pod hand off long-running work (COLMAP SfM, gsplat
training) to a pool of GPU worker pods without blocking, and survive
worker crashes without losing state.

Design principles
-----------------
* **Durable in Postgres, not Redis.** Redis Streams / RabbitMQ are the
  *transport*; the source of truth stays in Postgres so a queue reset
  never loses jobs.
* **Explicit lease semantics.** A worker "claims" a job by acquiring a
  lease with an expiry timestamp. If the worker dies, the lease expires
  and another worker can pick it up.
* **Retry counter, not blind requeue.** Repeated failures should not
  ping-pong forever — we cap ``attempts`` and move to ``dead``.
* **Idempotent completion.** Workers that were slow (past their lease)
  may still try to complete a job. The completion path detects stale
  workers and refuses their update.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


JOB_KINDS: tuple[str, ...] = ("colmap", "training", "export")

JOB_STATUSES: tuple[str, ...] = (
    "queued",     # in queue, no worker yet
    "leased",     # claimed by a worker, lease active
    "running",    # worker reports progress
    "succeeded",  # terminal
    "failed",     # terminal (may be retried by admin)
    "dead",       # too many attempts, admin only
    "canceled",   # user/admin canceled
)

MAX_ATTEMPTS = 3


class SceneJob(Base):
    __tablename__ = "scene_jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('colmap','training','export')",
            name="ck_scene_job_kind",
        ),
        CheckConstraint(
            "status IN ('queued','leased','running','succeeded','failed','dead','canceled')",
            name="ck_scene_job_status",
        ),
        # Fast path: workers claim jobs by (kind, status='queued', priority desc, created asc)
        Index("ix_scene_jobs_claim", "kind", "status", "priority", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    scene_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued", default="queued", index=True,
    )
    # Higher runs first. Default 0. Use 10 for interactive, -10 for batch.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Lease bookkeeping
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    leased_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, index=True)

    # Retry state
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result summary — worker fills these on success
    result_n_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_n_gaussians: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_psnr: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
