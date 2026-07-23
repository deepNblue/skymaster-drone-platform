"""Community playbooks — user-uploaded workflow templates.

Revision ID: 20260716_0027
Revises: 20260716_0026
Create Date: 2026-07-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260716_0027"
down_revision = "20260716_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_playbooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("dsl_yaml", sa.Text(), nullable=False),
        sa.Column(
            "sample_inputs_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(40)),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
        # Moderation state machine.
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("rejected_reason", sa.String(500), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Social signals.
        sa.Column(
            "install_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_community_playbook_status",
        ),
    )
    # Fast queries: "list approved playbooks by newest".
    op.create_index(
        "ix_community_playbooks_status_created",
        "community_playbooks",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_community_playbooks_status_created",
        table_name="community_playbooks",
    )
    op.drop_table("community_playbooks")
