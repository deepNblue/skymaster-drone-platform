"""F4.1 · Copilot v2 turn feedback — thumbs up/down + comment.

Enables tracking which Copilot replies users found helpful, so we can
improve intent parsing and reply generation. One feedback per user per
turn (upsert-style).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


RATING_UP = "up"
RATING_DOWN = "down"
VALID_RATINGS = (RATING_UP, RATING_DOWN)


class CopilotTurnFeedback(Base):
    __tablename__ = "copilot_turn_feedback"
    __table_args__ = (
        UniqueConstraint(
            "turn_id", "user_id", name="uq_feedback_turn_user",
        ),
        CheckConstraint(
            "rating IN ('up', 'down')",
            name="ck_feedback_rating",
        ),
        Index("ix_feedback_turn", "turn_id"),
        Index("ix_feedback_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    turn_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("copilot_turns_v2.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(), onupdate=func.now(),
    )
