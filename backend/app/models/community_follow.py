"""F3.3 · Community user follow relationship model.

Composite PK (follower_id, followed_id) — one user follows another
at most once. Both FKs cascade from users.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CommunityFollow(Base):
    """Directional follow: follower_id → followed_id."""
    __tablename__ = "community_follows"
    __table_args__ = (
        CheckConstraint(
            "follower_id <> followed_id",
            name="ck_follow_no_self",
        ),
    )

    follower_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    followed_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
