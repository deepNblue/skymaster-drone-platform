"""SQLAlchemy ORM: Drone."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Drone(Base):
    __tablename__ = "drones"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization.id"), index=True
    )
    sn: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    model: Mapped[str | None] = mapped_column(String(60))
    protocol: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str | None] = mapped_column(
        String(20), server_default="offline", index=True
    )
    # Column name is `metadata` in DB; attribute renamed to avoid SA reserved word.
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
