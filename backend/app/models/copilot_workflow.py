"""ORM model for stored Copilot workflows (T10.5 · v2.1 E2.1)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CopilotWorkflow(Base):
    """A user-authored Copilot workflow DSL document.

    * ``dsl_yaml`` is the source of truth — the raw text the author
      wrote. Parsing happens at read-time so schema changes don't
      require a re-save.
    * ``version`` is an optimistic-lock counter: every UPDATE must
      pass the current value; the service layer bumps it on write.
    * Soft delete via ``deleted_at`` — audit trails and referenced
      run traces stay valid.
    """

    __tablename__ = "copilot_workflows"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), index=True, nullable=True
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(
        String(1024), nullable=False, default="",
        server_default=text("''"),
    )
    dsl_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=_utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=_utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    __table_args__ = (
        # Partial unique — only alive rows contribute. This mirrors the
        # Postgres partial-index behaviour used by Alembic migration
        # ``20260716_0024_copilot_workflows.py`` so ORM ``create_all``
        # (used by SQLite tests) matches production semantics.
        Index(
            "ux_copilot_workflows_org_name_alive",
            "org_id", "name",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
