"""E2.5b · Airspace calendar — 空域占用日历.

Revision ID: 20260716_0029
Revises: 20260716_0028
Create Date: 2026-07-16

Rationale
=========
Roadmap §3.14 lists ``airspace_calendar`` alongside ``approval_templates``
as a v2.0 P0 table. This is the space-time occupancy table that answers
"can I fly a 3km radius circle around (30.5, 103.0) between 08:00 and
10:00 today?" without hitting the (rate-limited, sometimes offline)
UOM API for every conflict check.

Design
------
* One row per (approval OR external NOTAM OR internal reservation) that
  reserves a chunk of airspace for a time window.
* ``geo_polygon`` stored as JSON — GeoAlchemy/PostGIS is a v2.1 upgrade.
  For now we do bounding-box conflict detection at the service layer,
  which is O(N) but N stays small (<1000/day per city).
* ``source`` distinguishes UOM (authoritative), NOTAM (advisory), and
  local reservations (our own approved flight_approvals).
* Soft delete via deleted_at because history matters for audit.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260716_0029"
down_revision = "20260716_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "airspace_calendar",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column(
            "approval_id", postgresql.UUID(as_uuid=True),
            nullable=True, index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(255), nullable=True),
        sa.Column("geo_polygon", sa.JSON(), nullable=False),
        # Cached bounding box for cheap conflict detection.
        sa.Column("bbox_min_lon", sa.Float(), nullable=False),
        sa.Column("bbox_min_lat", sa.Float(), nullable=False),
        sa.Column("bbox_max_lon", sa.Float(), nullable=False),
        sa.Column("bbox_max_lat", sa.Float(), nullable=False),
        sa.Column("min_alt_m", sa.Float(), nullable=True),
        sa.Column("max_alt_m", sa.Float(), nullable=True),
        sa.Column("start_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "priority", sa.Integer(), nullable=False,
            server_default="10",
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source IN ('uom','notam','local','manual')",
            name="ck_airspace_calendar_source",
        ),
        sa.CheckConstraint(
            "end_ts > start_ts",
            name="ck_airspace_calendar_time_order",
        ),
    )
    # Idx for the hot query: "conflicts for (org, time_range, bbox)".
    op.create_index(
        "ix_airspace_calendar_time",
        "airspace_calendar",
        ["org_id", "start_ts", "end_ts"],
    )
    op.create_index(
        "ix_airspace_calendar_bbox",
        "airspace_calendar",
        ["bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat"],
    )


def downgrade() -> None:
    op.drop_index("ix_airspace_calendar_bbox", table_name="airspace_calendar")
    op.drop_index("ix_airspace_calendar_time", table_name="airspace_calendar")
    op.drop_table("airspace_calendar")
