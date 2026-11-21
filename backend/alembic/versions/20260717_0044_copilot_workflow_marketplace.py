"""copilot_workflow_marketplace tables (v2.1 E2.6)

Revision ID: 20260717_0044
Revises: 20260717_0043
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260717_0044"
down_revision = "20260717_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_workflow_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("workflow_version", sa.Integer, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("summary", sa.String(2048), nullable=False, server_default=""),
        sa.Column("tags", postgresql.JSONB),
        sa.Column("dsl_yaml_snapshot", sa.Text, nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("install_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_rating", sa.Float, nullable=False, server_default="0"),
        sa.Column("rating_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("unpublished_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index(
        "ix_copilot_workflow_listings_visibility_alive",
        "copilot_workflow_listings",
        ["visibility"],
        postgresql_where=sa.text("unpublished_at IS NULL"),
    )

    op.create_table(
        "copilot_workflow_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("rater_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rater_org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("stars", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("listing_id", "rater_user_id", name="uq_wl_rating_once"),
    )

    op.create_table(
        "copilot_workflow_installs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("installer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installer_org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("new_workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("copilot_workflow_installs")
    op.drop_table("copilot_workflow_ratings")
    op.drop_index(
        "ix_copilot_workflow_listings_visibility_alive",
        table_name="copilot_workflow_listings",
    )
    op.drop_table("copilot_workflow_listings")
