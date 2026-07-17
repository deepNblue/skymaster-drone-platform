"""SQLAlchemy ORM: CopilotApproval (SDD v2.0-C §5)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotApproval(Base):
    __tablename__ = "copilot_approvals"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trace_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    required_reason: Mapped[str | None] = mapped_column(Text)
    approver_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(20))
    modifications: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(Text)
