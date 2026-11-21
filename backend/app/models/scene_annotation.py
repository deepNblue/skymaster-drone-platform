"""D2.2 · Scene annotation models — 3DGS/4DGS markup layer.

Two tables:
  * ``SceneAnnotation``: markup on a scene (point/line/polygon/volume)
  * ``SceneAnnotationReply``: threaded discussion under an annotation

See ``20260717_0031_scene_annotations.py`` for schema rationale.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_GEOM_KINDS = frozenset({"point", "line", "polygon", "volume"})
VALID_SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})


class SceneAnnotation(Base):
    __tablename__ = "scene_annotation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    geom_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    geom_vertices: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False,
    )
    color: Mapped[str] = mapped_column(
        String(9), nullable=False, default="#22d3ee",
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info",
    )
    frame_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    layer: Mapped[str] = mapped_column(
        String(40), nullable=False, default="default",
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
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
        CheckConstraint(
            "geom_kind IN ('point','line','polygon','volume')",
            name="ck_ann_geom_kind",
        ),
        CheckConstraint(
            "severity IN ('info','low','medium','high','critical')",
            name="ck_ann_severity",
        ),
    )


class SceneAnnotationReply(Base):
    __tablename__ = "scene_annotation_reply"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scene_annotation.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
