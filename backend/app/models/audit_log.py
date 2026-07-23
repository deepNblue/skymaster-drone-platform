"""SQLAlchemy ORM: AuditLog (append-only)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Identity, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    ts: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(120))
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    ua: Mapped[str | None] = mapped_column(Text)
    # --- 国密 R18 tamper-evident hash chain + optional ciphertext ---------
    # Populated only when compliance_gateway is enabled for "audit_log".
    # Both are hex-encoded so they stay portable across DB backends.
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    curr_hash: Mapped[str | None] = mapped_column(String(64))
    diff_ct: Mapped[str | None] = mapped_column(Text)
    # --- R21 F: SM2 non-repudiation signature (over curr_hash + ts) --------
    # sig_hex: hex-encoded SM2 signature; sig_key_id: which platform keyset
    # produced it — verifiers look up the matching public key by ID.
    sig_hex: Mapped[str | None] = mapped_column(String(160))
    sig_key_id: Mapped[str | None] = mapped_column(String(32))
