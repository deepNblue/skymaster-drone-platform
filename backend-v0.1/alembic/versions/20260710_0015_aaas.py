"""aaas_clients + aaas_deliveries — R21 Step E.

Approval-as-a-Service subscriber registry and delivery ledger.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0015"
down_revision: Union[str, None] = "20260710_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "aaas_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("callback_url", sa.String(512), nullable=False),
        sa.Column("secret", sa.String(80), nullable=False),
        sa.Column("events", postgresql.JSONB, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_aaas_clients_active", "aaas_clients", ["active"])
    op.create_index("ix_aaas_clients_created_by", "aaas_clients", ["created_by"])

    op.create_table(
        "aaas_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("aaas_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_status_code", sa.Integer, nullable=True),
        sa.Column("last_response", sa.Text, nullable=True),
        sa.Column("last_signature", sa.String(96), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_aaas_deliveries_client_id", "aaas_deliveries", ["client_id"])
    op.create_index("ix_aaas_deliveries_event", "aaas_deliveries", ["event"])
    op.create_index("ix_aaas_deliveries_event_id", "aaas_deliveries", ["event_id"])
    op.create_index("ix_aaas_deliveries_approval_id", "aaas_deliveries", ["approval_id"])
    op.create_index("ix_aaas_deliveries_status", "aaas_deliveries", ["status"])
    op.create_index("ix_aaas_deliveries_next_attempt", "aaas_deliveries", ["next_attempt_at"])
    op.create_index(
        "ix_aaas_deliveries_client_event", "aaas_deliveries", ["client_id", "event"],
    )
    op.create_index(
        "ix_aaas_deliveries_status_next", "aaas_deliveries", ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("aaas_deliveries")
    op.drop_table("aaas_clients")
