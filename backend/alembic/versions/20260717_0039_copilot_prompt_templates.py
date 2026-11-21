"""F4.2 · Copilot prompt templates.

Revision ID: 20260717_0039
Revises: 20260717_0038
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0039"
down_revision = "20260717_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_prompt_templates",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("persona", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "is_active", sa.Boolean, nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "persona", "version", name="uq_prompt_persona_version",
        ),
        sa.CheckConstraint(
            "persona IN ('operator', 'analyst', 'instructor')",
            name="ck_prompt_persona",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_prompt_version_positive",
        ),
    )
    op.create_index(
        "ix_prompt_persona_active", "copilot_prompt_templates",
        ["persona", "is_active"],
    )
    op.create_index(
        "ix_prompt_persona_created", "copilot_prompt_templates",
        ["persona", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_persona_created",
        table_name="copilot_prompt_templates",
    )
    op.drop_index(
        "ix_prompt_persona_active",
        table_name="copilot_prompt_templates",
    )
    op.drop_table("copilot_prompt_templates")
