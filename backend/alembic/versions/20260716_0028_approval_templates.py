"""E2.5 · Flight approval templates — 合规报备模板

Revision ID: 20260716_0028
Revises: 20260716_0027
Create Date: 2026-07-16

Rationale
=========
Roadmap §3.14 lists ``approval_templates`` as a v2.0 P0 table for
飞行报备审批. Pilots doing 巡线/测绘/警务 all fill in the same
15-field UOM form 8 times a month. This table lets an org author
save-once/apply-many.

A template stores every human-entered field on a flight_approvals
row that is orthogonal to the actual flight time/location (which
DOES change per flight):

  * category, purpose
  * pilot_name/license, aircraft_reg/model, insurance_no
  * max_alt_m / min_alt_m (default cruise envelope)
  * authorities preset (UOM, local_police, ATC, forestry, etc.)
  * optional area_polygon default (e.g. patrol route that repeats)
  * checklist_json for "things the pilot must confirm"

Applying is a two-step: pilot picks a template + fills in the
delta (start_ts, end_ts, actual polygon override), server merges
& returns a normal flight_approvals row.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260716_0028"
down_revision = "20260716_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(255), nullable=True),
        # Pilot & aircraft presets.
        sa.Column("pilot_name", sa.String(64), nullable=True),
        sa.Column("pilot_license", sa.String(64), nullable=True),
        sa.Column("aircraft_reg", sa.String(64), nullable=True),
        sa.Column("aircraft_model", sa.String(64), nullable=True),
        sa.Column("insurance_no", sa.String(64), nullable=True),
        # Optional envelope defaults.
        sa.Column("max_alt_m", sa.Float(), nullable=True),
        sa.Column("min_alt_m", sa.Float(), nullable=True),
        sa.Column("default_area_polygon", sa.JSON(), nullable=True),
        # Authorities preset — list of {code, name, channel, priority}.
        sa.Column("authorities_preset", sa.JSON(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        # Extra pilot checklist.
        sa.Column("checklist_json", sa.JSON(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("apply_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('routine','high_altitude','night','sensitive_area','emergency')",
            name="ck_approval_template_category",
        ),
    )
    op.create_index(
        "ix_approval_templates_org_name",
        "approval_templates",
        ["org_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_templates_org_name",
        table_name="approval_templates",
    )
    op.drop_table("approval_templates")
