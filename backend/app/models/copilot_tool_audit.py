"""SQLAlchemy ORM: CopilotToolAudit + CopilotOrgToolPolicy (v2.1 F4.4).

Every Copilot tool invocation is written to `copilot_tool_audits` regardless of
outcome (executed / blocked / approved / rejected).  Per-org policy lives in
`copilot_org_tool_policies` and drives the interception logic in
``app.services.copilot_tool_policy``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotToolAudit(Base):
    __tablename__ = "copilot_tool_audits"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    session_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), index=True
    )
    trace_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False)  # readonly|sensitive
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # low | medium | high | critical
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # executed | blocked | approval_required | rejected | error
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_preview: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), index=True
    )


class CopilotOrgToolPolicy(Base):
    """Per-org policy driving tool interception.

    - ``allowlist`` — if non-empty, ONLY tools in list are executable.
    - ``blocklist`` — tools always blocked (checked before allowlist).
    - ``max_risk_level`` — cap at low/medium/high/critical; anything above
      requires manual approval regardless of ``permission``.
    - ``require_approval_above`` — tier above which we force approval
      (e.g. ``high`` means high+critical must always go through approval).
    """

    __tablename__ = "copilot_org_tool_policies"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), unique=True, index=True)
    allowlist: Mapped[list[str] | None] = mapped_column(JSONB)
    blocklist: Mapped[list[str] | None] = mapped_column(JSONB)
    max_risk_level: Mapped[str | None] = mapped_column(String(20))
    require_approval_above: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
