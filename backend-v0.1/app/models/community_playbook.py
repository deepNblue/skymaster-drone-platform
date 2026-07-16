"""T11.2 · Community Playbook — user-uploaded workflow templates.

Design intent
=============
Seed playbooks (T11.1) ship with the platform — 6 hard-coded templates
covering the golden path (morning inspection, emergency response, etc).
But real domain knowledge lives with the users: a 3-year emergency
responder in Sichuan knows a MUCH better landslide-scan template than
whatever the backend team scripted from Google Maps.

This table lets any org upload their own playbook, other orgs approve
it into the shared library, and then "Save as..." fork it into their
own workflows table (existing flow, no changes).

Not doing yet
=============
* No versioning — an author can "update" but not "revert to v3". Add
  playbook_versions later if users ask.
* No ratings/likes — install_count is our only social signal.
* No org-scoped visibility — either it's private (unapproved) to the
  author's org, or it's globally visible (approved).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CommunityPlaybook(Base):
    __tablename__ = "community_playbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    #: Globally unique url-safe identifier (community namespace, not
    #: colliding with seed playbook slugs). We prefix "user-" at
    #: creation to keep the flat namespace legible.
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(
        String(500), nullable=False, default="",
    )
    dsl_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    sample_inputs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)).with_variant(JSON(), "sqlite"),
        nullable=False, default=list,
    )

    # Moderation state machine.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    rejected_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    install_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_community_playbook_status",
        ),
    )
