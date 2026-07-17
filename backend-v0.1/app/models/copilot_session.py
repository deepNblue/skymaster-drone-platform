"""SQLAlchemy ORM: CopilotSession (SDD v2.0-C §5).

A copilot session groups a series of traces (one per user message).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotSession(Base):
    __tablename__ = "copilot_sessions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    total_cost_cent: Mapped[int | None] = mapped_column(
        Integer, server_default=text("0")
    )
    total_tokens: Mapped[int | None] = mapped_column(
        Integer, server_default=text("0")
    )
