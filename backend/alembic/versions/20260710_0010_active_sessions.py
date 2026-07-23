"""v2.0 R16 — active_sessions table for device management.

Revision ID: 20260710_0010
Revises: 20260710_0009
Create Date: 2026-07-10 07:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260710_0010"
down_revision: Union[str, None] = "20260710_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "active_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jti", sa.String(64), unique=True, nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("country", sa.String(4), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("device_label", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_active_sessions_user_id", "active_sessions", ["user_id"])
    op.create_index("ix_active_sessions_jti", "active_sessions", ["jti"])
    op.create_index("ix_active_sessions_created_at", "active_sessions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_active_sessions_created_at", table_name="active_sessions")
    op.drop_index("ix_active_sessions_jti", table_name="active_sessions")
    op.drop_index("ix_active_sessions_user_id", table_name="active_sessions")
    op.drop_table("active_sessions")
