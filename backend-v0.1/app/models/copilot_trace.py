"""SQLAlchemy ORM: CopilotTrace (SDD v2.0-C §5).

Matches the existing `copilot_traces` table created in the initial migration.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import REAL, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotTrace(Base):
    __tablename__ = "copilot_traces"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    prompt: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float | None] = mapped_column(REAL)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
