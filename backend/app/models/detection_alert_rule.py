"""E3.3 · Detection alert rule model.

Persisted rule that fires when a detection cluster crosses configured
thresholds (member_count / peak_confidence / label match).
Actions currently supported: log-only, feishu (delivered via existing
feishu-push worker in v2.0).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_ACTIONS = frozenset({"log", "feishu", "sms"})


class DetectionAlertRule(Base):
    """A per-org detection alert rule.

    Semantics: when a cluster with matching ``label`` (or wildcard)
    has ``member_count >= min_member_count`` and
    ``peak_confidence >= min_peak_confidence``, action fires.
    Cooldown avoids alert storms (default 300s per rule).
    """
    __tablename__ = "detection_alert_rule"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Wildcard "*" matches any label.
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    min_member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3,
    )
    min_peak_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
