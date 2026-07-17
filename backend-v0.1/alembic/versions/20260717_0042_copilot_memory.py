"""copilot_memories (v2.1 E2.3)

Revision ID: 20260717_0042
Revises: 20260717_0041
Create Date: 2026-07-17 12:20:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260717_0042"
down_revision = "20260717_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="user"),
        sa.Column("key", sa.String(200), index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tags", postgresql.JSONB),
        sa.Column("meta", postgresql.JSONB),
        sa.Column("ttl_days", sa.Integer),
        sa.Column("weight", sa.Integer, nullable=False, server_default="50"),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            index=True,
        ),
        sa.Column("last_hit_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), index=True),
    )
    op.create_index(
        "ix_copilot_memories_org_user_kind",
        "copilot_memories",
        ["org_id", "user_id", "kind"],
    )
    op.create_index(
        "ix_copilot_memories_org_scope",
        "copilot_memories",
        ["org_id", "scope"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_memories_org_scope", table_name="copilot_memories"
    )
    op.drop_index(
        "ix_copilot_memories_org_user_kind", table_name="copilot_memories"
    )
    op.drop_table("copilot_memories")
