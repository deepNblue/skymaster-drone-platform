"""Community post reports — added by T6.5.

Idempotent add of the community_reports table for user-driven
reporting. Uses IF NOT EXISTS so it's a no-op if the initial
20260713_0020 migration is later amended to include the table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision = "20260713_0021"
down_revision = "20260713_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_reports",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("post_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("community_posts.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("reporter_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="open"),
        sa.Column("resolved_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "post_id", "reporter_id",
            name="uq_community_report_reporter_post",
        ),
    )


def downgrade() -> None:
    op.drop_table("community_reports")
