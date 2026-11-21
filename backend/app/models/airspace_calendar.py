"""E2.5b · Airspace calendar model.

Space-time occupancy row for conflict detection. See migration
``20260716_0029_airspace_calendar.py`` for design notes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, JSON, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_SOURCES = frozenset({"uom", "notam", "local", "manual"})


class AirspaceCalendarEntry(Base):
    __tablename__ = "airspace_calendar"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geo_polygon: Mapped[list] = mapped_column(JSON, nullable=False)
    bbox_min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    end_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10,
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
            "source IN ('uom','notam','local','manual')",
            name="ck_airspace_calendar_source",
        ),
        CheckConstraint(
            "end_ts > start_ts",
            name="ck_airspace_calendar_time_order",
        ),
    )
