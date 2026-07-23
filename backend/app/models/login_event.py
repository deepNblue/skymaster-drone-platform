"""LoginEvent model — per-attempt login/logout audit trail.

Distinct from AuditLog (which tracks mutating API calls). LoginEvents
capture every authentication touchpoint: password login, SSO login,
refresh, logout, and TOTP verification — with outcome, IP, UA, and
geoip-derived country for anomaly detection.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # e.g. "password", "sso:google", "sso:github", "refresh", "logout", "totp"
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    # "success", "invalid_password", "invalid_totp", "locked", "rate_limit"
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(4), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Free-form JSON for extra context (e.g. sso_sub, provider).
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
