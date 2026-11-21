"""ORM model for the copilot_workflow_runs audit table (T10.8).

Kept intentionally lean: this table is append-only and read via
list/detail endpoints; no relationships are declared so we can survive
soft-deleted parent workflows without cascading complexity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CopilotWorkflowRun(Base):
    __tablename__ = "copilot_workflow_runs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid4,
    )
    # nullable to survive tests where user has no org
    org_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    # Nullable — inline runs have no saved workflow row to point at.
    workflow_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True,
    )
    workflow_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSONB in Postgres; SQLite maps to TEXT via conftest's compile hook.
    # We always populate this at insert time. Python default is enough
    # to satisfy both dialects — server_default would emit a Postgres
    # JSONB literal that SQLite chokes on.
    trace_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        default=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        # Mirror the Alembic indexes so SQLite create_all builds them.
        Index(
            "ix_copilot_workflow_runs_org_started",
            "org_id", "started_at",
        ),
        Index(
            "ix_copilot_workflow_runs_wf_started",
            "workflow_id", "started_at",
        ),
    )
