"""F4.2 · Copilot v2 prompt template — versioned system prompts.

Enables ops to iterate Copilot behavior without code deploys. Each
persona (operator/analyst/instructor) has a chain of versions; exactly
one version per persona may be marked active.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_PERSONAS = ("operator", "analyst", "instructor")


class CopilotPromptTemplate(Base):
    """Versioned system prompt per persona."""
    __tablename__ = "copilot_prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "persona", "version", name="uq_prompt_persona_version",
        ),
        CheckConstraint(
            "persona IN ('operator', 'analyst', 'instructor')",
            name="ck_prompt_persona",
        ),
        CheckConstraint(
            "version >= 1", name="ck_prompt_version_positive",
        ),
        Index("ix_prompt_persona_active", "persona", "is_active"),
        Index(
            "ix_prompt_persona_created", "persona", "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    persona: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
