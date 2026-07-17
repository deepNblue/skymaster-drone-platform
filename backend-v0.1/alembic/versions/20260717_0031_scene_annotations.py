"""D2.2 · Scene annotations — 3DGS/4DGS scene markup layer.

Revision ID: 20260717_0031
Revises: 20260716_0030
Create Date: 2026-07-17

Rationale
=========
Reality Studio (E2) reconstructs 3DGS / 4DGS scenes. Ops teams (grid
inspection, dam safety, agri) then need to **annotate** those scenes —
mark defect points, measure distances, add textual notes, share with
peers.

This module adds two tables:
  * ``scene_annotation``: individual markup entries (point / line /
    polygon / volume + label + severity + author).
  * ``scene_annotation_reply``: threaded discussion under an annotation
    (for collaborative review).

Kept minimal: geometry is stored as JSONB coordinate lists — same
convention as ``area_polygon`` in flight_approval. Alembic +
model + service + REST + tests in one wave.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0031"
down_revision = "20260716_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scene_annotation",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scene_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("geom_kind", sa.String(16), nullable=False),
        # geom = list of [x, y, z] triples in the scene's local ENU frame.
        # point -> 1 vertex; line -> ≥2; polygon -> ≥3 (closed);
        # volume -> at least 3 vertices + explicit meta.height
        sa.Column(
            "geom_vertices", postgresql.JSONB(), nullable=False,
        ),
        # Colour hex "#RRGGBB" for viewer rendering. Default cyan.
        sa.Column(
            "color", sa.String(9), nullable=False,
            server_default="#22d3ee",
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "severity", sa.String(16),
            nullable=False, server_default="info",
        ),
        # 4DGS: pin annotation to a specific frame index. NULL = static.
        sa.Column("frame_index", sa.Integer(), nullable=True),
        # Layer namespace for viewer UI (e.g. "defect", "sensor", "note").
        sa.Column(
            "layer", sa.String(40),
            nullable=False, server_default="default",
        ),
        sa.Column(
            "meta", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "resolved", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "geom_kind IN ('point','line','polygon','volume')",
            name="ck_ann_geom_kind",
        ),
        sa.CheckConstraint(
            "severity IN ('info','low','medium','high','critical')",
            name="ck_ann_severity",
        ),
    )
    op.create_index(
        "ix_scene_ann_scene_layer",
        "scene_annotation",
        ["scene_id", "layer"],
    )

    op.create_table(
        "scene_annotation_reply",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "annotation_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"], ["scene_annotation.id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("scene_annotation_reply")
    op.drop_index("ix_scene_ann_scene_layer", table_name="scene_annotation")
    op.drop_table("scene_annotation")
