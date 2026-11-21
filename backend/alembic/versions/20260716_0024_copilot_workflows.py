"""T10.5 (v2.1 E2.1) — copilot_workflows persistence.

Introduces the ``copilot_workflows`` table so users can save/list/update
DSL documents rather than passing the full YAML on every /run.

Design notes
============
* ``org_id`` scoping mirrors every other v2 tenant-aware table. NULL
  is permitted for legacy/self-only rows but production paths always
  populate it from the JWT.
* ``dsl_yaml`` stores the raw YAML the author wrote — we deliberately
  keep the original text so the editor can round-trip comments and
  whitespace. The parsed structure is *not* persisted; validation
  runs on every fetch.
* ``version`` is an integer optimistic-lock counter, bumped by every
  UPDATE. Two concurrent editors will see a 409 on the second save.
* Soft delete via ``deleted_at`` so audit trails survive.
* A unique index over ``(org_id, name)`` (partial: not-deleted only)
  prevents duplicate names inside a tenant without blocking name reuse
  after soft-delete.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers.
revision = "20260716_0024"
down_revision = "20260716_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_workflows",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("dsl_yaml", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("created_at", pg.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", pg.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", pg.TIMESTAMP(timezone=True), nullable=True),
    )
    # Partial unique — only alive rows contribute.
    op.create_index(
        "ux_copilot_workflows_org_name_alive",
        "copilot_workflows",
        ["org_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_copilot_workflows_owner",
        "copilot_workflows",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_workflows_owner", table_name="copilot_workflows"
    )
    op.drop_index(
        "ux_copilot_workflows_org_name_alive",
        table_name="copilot_workflows",
    )
    op.drop_table("copilot_workflows")
