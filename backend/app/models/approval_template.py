"""E2.5 · Flight approval template — 合规报备模板.

Roadmap §3.14 lists this as a v2.0 P0 asset alongside flight_approvals.
Pilots doing recurring 巡线/测绘/警务 flights fill in the same
UOM form fields 8 times a month; this lets them save-once and
apply-many.

Design notes
============
* Author-owned per-org (unique name within org, soft-deletable).
* The ``authorities_preset`` mirrors the FlightApprovalAuthority
  shape but stored as JSON (we don't need normalization for a template).
* ``default_area_polygon`` optional — some templates are truly a
  fixed patrol route; most are envelope-only.
* ``apply_count`` bumps every time the template creates a real
  flight_approval — a soft popularity signal for UI ranking.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint, DateTime, Float, Integer, JSON, String, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_CATEGORIES = frozenset({
    "routine",
    "high_altitude",
    "night",
    "sensitive_area",
    "emergency",
})


class ApprovalTemplate(Base):
    __tablename__ = "approval_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="routine",
    )
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pilot_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pilot_license: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aircraft_reg: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aircraft_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insurance_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_area_polygon: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
    )
    authorities_preset: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list,
    )
    checklist_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list,
    )
    apply_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('routine','high_altitude','night',"
            "'sensitive_area','emergency')",
            name="ck_approval_template_category",
        ),
    )
