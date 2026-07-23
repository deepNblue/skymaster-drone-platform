"""T10.8 (v2.1 E2.1) — copilot_workflow_runs audit trail.

Every ``/run`` and ``/{id}/run`` invocation is persisted here so users
can browse history from the frontend, correlate failures, and (later)
export for compliance. Complements the run **trace** returned to the
caller — that is transient and lives only in the response.

Design notes
============
* Runs are **immutable append-only**: no UPDATE or DELETE endpoints.
  This is an audit table; we care about durability over churn.
* ``workflow_id`` is nullable — inline runs (T10.3 ``/run``) have no
  saved workflow to reference. Stored runs (T10.5 ``/{id}/run``) point
  back to the source row.
* Since ``copilot_workflows`` is soft-deleted, the FK is intentionally
  not declared here — a deleted workflow's runs must remain queryable
  even after the row is gone. We store ``workflow_id`` as a bare UUID
  column with a plain b-tree index.
* ``trace_json`` holds the full ``RunResponse`` shape (steps + errors
  + timings). ~50KB max on hot path; store as JSONB to allow filtering
  by status without deserializing.
* Two indexes:
    (org_id, started_at DESC) — the primary "recent history" scan
    (workflow_id, started_at DESC) — "runs of this workflow" view
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers.
revision = "20260716_0025"
down_revision = "20260716_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_workflow_runs",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=True),
        # Nullable — inline runs have no saved workflow row.
        sa.Column("workflow_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_name", sa.String(length=256), nullable=False),
        # 'ok' | 'failed' — matches WorkflowRun.status
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_json", pg.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", pg.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_copilot_workflow_runs_org_started",
        "copilot_workflow_runs",
        ["org_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_copilot_workflow_runs_wf_started",
        "copilot_workflow_runs",
        ["workflow_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_workflow_runs_wf_started",
        table_name="copilot_workflow_runs",
    )
    op.drop_index(
        "ix_copilot_workflow_runs_org_started",
        table_name="copilot_workflow_runs",
    )
    op.drop_table("copilot_workflow_runs")
