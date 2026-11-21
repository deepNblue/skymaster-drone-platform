"""D3.1 · 4DGS scene frame model — per-frame temporal metadata."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_LIGHTING = frozenset({
    "day", "dusk", "night", "overcast", "sunrise", "sunset",
})


class SceneFrame(Base):
    __tablename__ = "scene_frame"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
    )
    frame_index: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    is_keyframe: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    psnr_frame: Mapped[float | None] = mapped_column(Float)
    lighting: Mapped[str | None] = mapped_column(String(24))
    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "scene_id", "frame_index", name="uq_scene_frame_scene_idx",
        ),
        CheckConstraint(
            "frame_index >= 0", name="ck_scene_frame_nonneg",
        ),
    )
