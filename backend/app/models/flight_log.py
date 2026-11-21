"""SQLAlchemy ORM: FlightLog (TimescaleDB hypertable).

Note: flight_logs has no primary key in the migration; SQLAlchemy requires one
for a mapped class. We declare a composite mapper-level PK on (time, drone_id)
that mirrors the natural key without emitting DDL (no PK constraint exists in DB).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Float, REAL, SmallInteger, String
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FlightLog(Base):
    __tablename__ = "flight_logs"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    drone_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, nullable=False
    )
    mission_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    lat: Mapped[float | None] = mapped_column(Float(precision=53))
    lng: Mapped[float | None] = mapped_column(Float(precision=53))
    alt: Mapped[float | None] = mapped_column(REAL)
    speed: Mapped[float | None] = mapped_column(REAL)
    heading: Mapped[float | None] = mapped_column(REAL)
    roll: Mapped[float | None] = mapped_column(REAL)
    pitch: Mapped[float | None] = mapped_column(REAL)
    yaw: Mapped[float | None] = mapped_column(REAL)
    battery_pct: Mapped[float | None] = mapped_column(REAL)
    rssi: Mapped[int | None] = mapped_column(SmallInteger)
    gps_sats: Mapped[int | None] = mapped_column(SmallInteger)
    flight_mode: Mapped[str | None] = mapped_column(String(20))
