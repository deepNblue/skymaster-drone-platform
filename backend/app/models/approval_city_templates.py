"""Per-city approval templates for AAS v2.3 production.

v2.3 E7: Approval-as-a-Service 生产级扩展 — 30+ 重点城市报备模板适配.

Each city can have:
- Custom form fields required by local police
- Email template for manual submission
- RPA selectors if the city has online portal
- Status reply parsing rules (email subject/content patterns)
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CityApprovalTemplate(Base):
    """Pre-configured approval template for a Chinese city.

    Users from this city get auto-filled form according to local requirements.
    """

    __tablename__ = "approval_city_templates"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    province: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    city_adcode: Mapped[str | None] = mapped_column(String(12), nullable=True)  # 行政区划代码
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Required form fields list — frontend shows these in order
    required_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Field labels in Chinese
    field_labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Submission channel
    submission_channel: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="email",
    )  # email / online-rpa / paper

    # Email submission config
    target_email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_subject_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_body_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Online RPA config (selector for playwright)
    rpa_login_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    rpa_selectors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Status reply parsing
    # Patterns to match in email subject/body for each status
    approve_patterns: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    reject_patterns: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Notes for maintainers
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last tested date
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class ApprovalStatusReceipt(Base):
    """Parsed status receipt from email or online portal.

    Stored separately from main approval for audit history.
    """

    __tablename__ = "approval_status_receipts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    approval_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("flight_approvals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    city_template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("approval_city_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # email / manual / portal
    parsed_status: Mapped[str] = mapped_column(String(16), nullable=False)  # approved / rejected / received
    raw_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_from_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    manually_updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
