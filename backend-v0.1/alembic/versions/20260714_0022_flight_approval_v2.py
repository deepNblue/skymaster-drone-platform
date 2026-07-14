"""T7.0 — Flight approval v2.0 enhancements.

Adds three columns to ``flight_approvals`` (second-approval trio) and
introduces ``flight_approval_signatures`` for e-sign audit trail.

Second-approval semantics
-------------------------
Set when the router flags a submission as high-risk (emergency /
special / >120m / polygon > 1 km²). The submit endpoint transitions
to status ``pending_second_approval`` instead of ``submitted`` and
holds the fan-out until a supervisor approves.

Signature semantics
-------------------
E-sign is per-authority-decision. Records signer_user_id, sha256 of
the payload the signer saw, algorithm, and timestamp. Multiple
signatures per authority allowed (audit chain).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers.
revision = "20260714_0022"
down_revision = "20260713_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flight_approvals",
        sa.Column("requires_second_approval", sa.Boolean(),
                  server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "flight_approvals",
        sa.Column("second_approver_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "flight_approvals",
        sa.Column("second_approved_at",
                  sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "flight_approval_signatures",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("approval_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("flight_approvals.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("authority_code", sa.String(32), nullable=True),
        sa.Column("signer_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("signer_role", sa.String(32), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False,
                  server_default="sha256"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("flight_approval_signatures")
    op.drop_column("flight_approvals", "second_approved_at")
    op.drop_column("flight_approvals", "second_approver_id")
    op.drop_column("flight_approvals", "requires_second_approval")
