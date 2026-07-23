"""AI Model Marketplace tables — v2.0 Track E."""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0018"
down_revision: Union[str, None] = "20260710_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("framework", sa.String(32), nullable=False),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("owner_org_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                    nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True),
        sa.Column("license", sa.String(32), nullable=False, server_default="proprietary"),
        sa.Column("price_model", sa.String(16), nullable=False, server_default="free"),
        sa.Column("price_unit", sa.Numeric(12, 6), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_listings_task", "model_listings", ["task"])
    op.create_index("ix_model_listings_visibility", "model_listings", ["visibility"])
    op.create_index("ix_model_listings_owner_org", "model_listings", ["owner_org_id"])

    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("model_listings.id", ondelete="CASCADE"),
                    nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("artifact_uri", sa.String(1024), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("inputs_schema", postgresql.JSONB, nullable=True),
        sa.Column("outputs_schema", postgresql.JSONB, nullable=True),
        sa.Column("hardware", postgresql.JSONB, nullable=True),
        sa.Column("benchmark", postgresql.JSONB, nullable=True),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("listing_id", "version", name="uq_model_version"),
    )
    op.create_index("ix_model_versions_listing_id", "model_versions", ["listing_id"])
    op.create_index("ix_model_versions_review_status", "model_versions", ["review_status"])

    op.create_table(
        "model_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                    nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("model_listings.id", ondelete="CASCADE"),
                    nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
                    nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="installed"),
        sa.Column("endpoint_url", sa.String(1024), nullable=True),
        sa.Column("quota_calls_per_day", sa.Integer, nullable=True),
        sa.Column("installed_by", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "listing_id", name="uq_org_listing"),
    )
    op.create_index("ix_model_deployments_org_id", "model_deployments", ["org_id"])
    op.create_index("ix_model_deployments_listing_id", "model_deployments", ["listing_id"])
    op.create_index("ix_model_deployments_version_id", "model_deployments", ["version_id"])
    op.create_index("ix_model_deployments_status", "model_deployments", ["status"])

    op.create_table(
        "model_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("model_deployments.id", ondelete="CASCADE"),
                    nullable=False),
        sa.Column("units", sa.Integer, nullable=False),
        sa.Column("unit_type", sa.String(16), nullable=False),
        sa.Column("latency_ms", sa.Numeric(12, 3), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("meta", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                    server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_usage_events_deployment_id", "model_usage_events", ["deployment_id"])
    op.create_index("ix_model_usage_events_created_at", "model_usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("model_usage_events")
    op.drop_table("model_deployments")
    op.drop_table("model_versions")
    op.drop_table("model_listings")
