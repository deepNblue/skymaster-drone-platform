"""FlightApproval — per PRODUCT_SPEC §3.14 one-stop multi-authority approval.

Represents a single flight request that fans out to N authority sub-tasks
(UOM / 属地公安 / 空管 / 林草 / 文旅 / 海事). Each authority is tracked in
``FlightApprovalAuthority`` rows and rolled up into an overall status.

State machine (top-level ``status``):

    draft → submitted → in_review → approved | rejected → flown → archived
                            │
                            └────→ cancelled

Per-authority sub-status is independent and drives the roll-up:

    pending → submitted → accepted → approving → approved | rejected

Rollup rule::

    if all authorities approved → approved
    if any authority rejected   → rejected
    if any authority not final  → in_review
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FlightApproval(Base):
    __tablename__ = "flight_approvals"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    mission_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # routine | special | emergency
    category: Mapped[str] = mapped_column(String(16), default="routine", nullable=False)
    # human-readable title + purpose for authority forms
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pilot_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pilot_license: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aircraft_reg: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aircraft_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insurance_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # airspace as GeoJSON polygon (list of [lng, lat])
    area_polygon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # draft | submitted | pending_second_approval | in_review | approved | rejected | flown | archived | cancelled
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False, index=True)
    reject_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # T7.0 second-approval trio ------------------------------------------
    requires_second_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
    )
    second_approver_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    second_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # append-only timeline events: [{ts, actor, action, note}]
    timeline: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    authorities: Mapped[list["FlightApprovalAuthority"]] = relationship(
        back_populates="approval", cascade="all, delete-orphan", lazy="selectin"
    )
    signatures: Mapped[list["FlightApprovalSignature"]] = relationship(
        back_populates="approval", cascade="all, delete-orphan", lazy="selectin"
    )


class FlightApprovalAuthority(Base):
    __tablename__ = "flight_approval_authorities"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    approval_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("flight_approvals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # uom | local_police | atc | forestry | tourism | maritime | market_regulator
    authority_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    authority_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # api | rpa | manual — how we submit
    channel: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    # pending | submitted | accepted | approving | approved | rejected | skipped
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    approval: Mapped[FlightApproval] = relationship(back_populates="authorities")


class FlightApprovalSignature(Base):
    """E-signature audit record — T7.0.

    A signer attaches their identity + a sha256 hash of the exact
    payload they saw. Multiple signatures per (approval, authority)
    are allowed; the sequence tells the audit story.
    """

    __tablename__ = "flight_approval_signatures"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    approval_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("flight_approvals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # None = signature on the whole approval (e.g., second approval);
    # otherwise the per-authority decision this seal endorses.
    authority_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    signer_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    signer_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(
        String(32), nullable=False, default="sha256",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    approval: Mapped[FlightApproval] = relationship(back_populates="signatures")
