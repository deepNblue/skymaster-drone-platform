"""F4.3 · Copilot usage & quota — per-tenant tokens/latency ledger.

Every Copilot turn writes one usage row (best-effort, fire-and-forget
from producer). Admin dashboards aggregate rollups; quota policy
determines whether new requests are throttled.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
    String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotUsage(Base):
    """One row per Copilot turn (or workflow call).

    Non-critical: producer writes fire-and-forget so a DB blip in the
    ledger never kills the user-facing request.
    """
    __tablename__ = "copilot_usage"
    __table_args__ = (
        CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0",
            name="ck_usage_tokens_nonneg",
        ),
        CheckConstraint(
            "latency_ms >= 0", name="ck_usage_latency_nonneg",
        ),
        CheckConstraint(
            "cost_units >= 0", name="ck_usage_cost_nonneg",
        ),
        Index(
            "ix_usage_org_created", "org_id", "created_at",
        ),
        Index(
            "ix_usage_persona_created", "persona", "created_at",
        ),
        Index(
            "ix_usage_status_created", "status", "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    persona: Mapped[str | None] = mapped_column(
        String(24), nullable=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    # Cost is priced in abstract units (1 unit = 1 credit); pricing
    # tier stored separately so we can back-price without table churn.
    cost_units: Mapped[float] = mapped_column(
        Numeric(12, 4), default=0, nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), default="ok", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class CopilotOrgQuota(Base):
    """Monthly token budget per org (a nullable ceiling)."""
    __tablename__ = "copilot_org_quota"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_org_quota"),
        CheckConstraint(
            "monthly_token_budget >= 0",
            name="ck_quota_budget_nonneg",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    monthly_token_budget: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    hard_stop: Mapped[bool] = mapped_column(
        default=False, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(), onupdate=func.now(),
    )
