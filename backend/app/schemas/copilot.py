"""Pydantic schemas for Copilot v0.1 endpoints (SDD v2.0-C §6)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ApprovalDecisionLiteral = Literal["approved", "rejected", "modified"]


class MessageRequest(BaseModel):
    """User message posted to a Copilot session."""

    prompt: str = Field(..., min_length=1, max_length=8000)


class TraceStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    tool: str
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    duration_ms: int | None = None
    error: str | None = None
    ts: datetime | None = None


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID | None = None
    prompt: str | None = None
    intent: str | None = None
    confidence: float | None = None
    status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    output: dict[str, Any] | None = None
    steps: list[TraceStepOut] | None = None


class ApprovalDecision(BaseModel):
    """Human decision on a Copilot approval gate."""

    decision: ApprovalDecisionLiteral
    modifications: dict[str, Any] | None = None
    comment: str | None = Field(default=None, max_length=2000)


__all__ = [
    "ApprovalDecision",
    "ApprovalDecisionLiteral",
    "MessageRequest",
    "TraceOut",
    "TraceStepOut",
]
