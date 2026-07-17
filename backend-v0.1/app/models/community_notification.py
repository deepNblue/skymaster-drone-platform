"""F3.4 · Community notification model — unified inbox."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# Notification kinds (extensible; validated at DB & service layer).
KIND_NEW_FOLLOWER = "new_follower"
KIND_POST_LIKED = "post_liked"
KIND_POST_REPLY = "post_reply"
KIND_MENTION = "mention"

VALID_KINDS = (
    KIND_NEW_FOLLOWER, KIND_POST_LIKED, KIND_POST_REPLY, KIND_MENTION,
)


class CommunityNotification(Base):
    __tablename__ = "community_notifications"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('new_follower', 'post_liked', "
            "'post_reply', 'mention')",
            name="ck_notification_kind",
        ),
        Index(
            "ix_notif_recipient_created",
            "recipient_id", "created_at",
        ),
        Index(
            "ix_notif_recipient_unread",
            "recipient_id", "read_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    recipient_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    post_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    comment_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
