"""v2.0 R9 — CopilotTrace.org_id NOT NULL + backfill.

Enforces org_id at DB level for tenant isolation. Existing NULL rows are
backfilled from the parent CopilotSession's org_id where available; any
remaining orphans are marked with a synthetic 'legacy-null' sentinel org
so the migration doesn't fail.

Revision ID: 20260710_0004
Revises: 20260710_0003
Create Date: 2026-07-10 03:35:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260710_0004"
down_revision: Union[str, None] = "20260710_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- Step 1: backfill copilot_traces.org_id from parent session -----
    conn.execute(
        sa.text("""
            UPDATE copilot_traces AS t
            SET org_id = s.org_id
            FROM copilot_sessions AS s
            WHERE t.session_id = s.id AND t.org_id IS NULL
        """)
    )

    # --- Step 2: seed sentinel org for orphans -------------------------
    #     Rare: traces without a session ref, or session without org.
    orphan_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM copilot_traces WHERE org_id IS NULL")
    ).scalar_one()
    if orphan_count and orphan_count > 0:
        sentinel_id = str(uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (:id, :name, NOW()) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"id": sentinel_id, "name": "__legacy_null_org__"},
        )
        # Fetch actual id if ON CONFLICT hit
        real_id = conn.execute(
            sa.text(
                "SELECT id FROM organizations WHERE name = '__legacy_null_org__'"
            )
        ).scalar_one()
        conn.execute(
            sa.text(
                "UPDATE copilot_traces SET org_id = :oid WHERE org_id IS NULL"
            ),
            {"oid": real_id},
        )

    # --- Step 3: make org_id NOT NULL ------------------------------------
    op.alter_column(
        "copilot_traces",
        "org_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_index(
        "ix_copilot_traces_org_status",
        "copilot_traces",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_copilot_traces_org_status", table_name="copilot_traces")
    op.alter_column(
        "copilot_traces",
        "org_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
