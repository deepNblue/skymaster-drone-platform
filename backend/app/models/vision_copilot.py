"""VisionDetection + CopilotSession models — v2.0 Track B R20.

**VisionDetection** — a single detection event emitted by the edge runtime.
   Persist selectively (thresholded / user-marked) so we don't drown storage.

**CopilotSession** / **CopilotTurn** — natural-language Copilot Agent conversation
   with tool-call turns; each turn stores the intent, extracted arguments,
   and the resulting mission/drone command that was actually executed.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VisionDetection(Base):
    __tablename__ = "vision_detections"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    drone_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    mission_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    stream_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g. "person", "vehicle", "fire", "solar_panel_defect"
    label: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # normalized [0,1] bbox
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # GPS position at detection instant, if available
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    alt_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frame_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Model tag & runtime backend
    model_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "new" | "acknowledged" | "dismissed" | "escalated"
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False, index=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CopilotSessionV2(Base):
    __tablename__ = "copilot_sessions_v2"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(128), default="新会话", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "operator" (自然语言操控) | "analyst" (报告/查询) | "instructor" (任务规划)
    persona: Mapped[str] = mapped_column(String(24), default="operator", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    turns: Mapped[list["CopilotTurnV2"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="CopilotTurnV2.turn_idx", lazy="selectin",
    )


class CopilotTurnV2(Base):
    __tablename__ = "copilot_turns_v2"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("copilot_sessions_v2.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    turn_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Parsed intent, e.g. "takeoff", "goto_waypoint", "return_to_home",
    # "start_recording", "search_and_query", "generate_report"
    intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Rendered natural-language reply
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether the tool call executed and what happened
    tool_call: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # "ok" | "clarify" | "denied" | "error"
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[CopilotSessionV2] = relationship(back_populates="turns")
