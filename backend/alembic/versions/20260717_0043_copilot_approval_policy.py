"""copilot_approval_policy + signoffs (v2.1 E2.5)

Revision ID: 20260717_0043
Revises: 20260717_0042
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260717_0043"
down_revision = "20260717_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_approval_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, index=True),
        sa.Column("dual_sign_tools", postgresql.JSONB),
        sa.Column("dual_sign_min_risk", sa.String(16)),
        sa.Column("required_roles", postgresql.JSONB),
        sa.Column("bypass_roles", postgresql.JSONB),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "copilot_approval_signoffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("signer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signer_role", sa.String(60)),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_copilot_approval_signoffs_approval_signer",
        "copilot_approval_signoffs",
        ["approval_id", "signer_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_approval_signoffs_approval_signer",
        table_name="copilot_approval_signoffs",
    )
    op.drop_table("copilot_approval_signoffs")
    op.drop_table("copilot_approval_policies")
