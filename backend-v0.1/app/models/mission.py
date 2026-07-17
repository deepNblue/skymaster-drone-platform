"""SQLAlchemy ORM: Mission."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization.id"), index=True
    )
    drone_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("drones.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    template: Mapped[str | None] = mapped_column(String(40))
    waypoints: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str | None] = mapped_column(
        String(20), server_default="draft", index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
