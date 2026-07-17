"""ORM for Copilot workflow schedules (T12.1 · v2.1 E2.2).

A schedule binds one stored workflow to a cron expression + fixed
inputs. The scheduler daemon (T12.2) polls ``next_fire_at`` and fires
runs via the same executor path as manual /run — so all safety gates
(sensitive tool approval, org isolation, run audit) still apply.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CopilotWorkflowSchedule(Base):
    __tablename__ = "copilot_workflow_schedules"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("copilot_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default=text("true"),
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    last_fire_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    last_fire_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
    )
    last_fire_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
