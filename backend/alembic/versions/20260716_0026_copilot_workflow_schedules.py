"""Copilot workflow schedules table · T12.1 (v2.1 E2.2).

The workflow engine (T10.x) and playbook seeds (T11.x) are in place — but
users still have to hit "Run" manually. compliance-patrol is documented
as "周度审计" yet has no way to fire weekly on its own.

This migration adds ``copilot_workflow_schedules``, an append-editable
schedule table where each row binds a workflow to a cron expression and
tracks the last / next fire times. The scheduler daemon (T12.2) will
poll this table; for now the API + model exists so the UI can already
manage rows.

Columns
-------
* ``id`` — UUID PK
* ``org_id`` — tenant scope (indexed, everything filters here)
* ``workflow_id`` — FK to copilot_workflows.id, CASCADE on delete
                   (deleting the source workflow drops its schedules —
                   audit history still lives in workflow_runs)
* ``cron_expr`` — 5-field cron like "0 9 * * MON"
* ``inputs_json`` — JSONB static inputs baked at schedule creation time
                    (a schedule is a workflow + fixed inputs)
* ``enabled`` — soft on/off toggle
* ``created_by`` — audit trail
* ``created_at`` / ``updated_at``
* ``last_fire_at`` — timestamptz, nullable (set by scheduler)
* ``last_fire_status`` — 'ok' | 'failed' | null
* ``last_fire_run_id`` — FK to copilot_workflow_runs.id, nullable
* ``next_fire_at`` — timestamptz, populated on insert/update from
                    cron_expr; scheduler queries this indexed column

Indexes
-------
* ``ix_copilot_workflow_schedules_org``          (org_id,)
* ``ix_copilot_workflow_schedules_next_fire``    (enabled, next_fire_at)
  — the scheduler hot-path index. Composite so 'enabled=true' filter is
  covered before the range scan.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision = "20260716_0026"
down_revision = "20260716_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_workflow_schedules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("copilot_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron_expr", sa.String(64), nullable=False),
        sa.Column(
            "inputs_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_fire_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_fire_status", sa.String(16), nullable=True),
        sa.Column(
            "last_fire_run_id",
            pg.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "next_fire_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_copilot_workflow_schedules_org",
        "copilot_workflow_schedules",
        ["org_id"],
    )
    op.create_index(
        "ix_copilot_workflow_schedules_next_fire",
        "copilot_workflow_schedules",
        ["enabled", "next_fire_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_workflow_schedules_next_fire",
        table_name="copilot_workflow_schedules",
    )
    op.drop_index(
        "ix_copilot_workflow_schedules_org",
        table_name="copilot_workflow_schedules",
    )
    op.drop_table("copilot_workflow_schedules")
