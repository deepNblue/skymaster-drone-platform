"""v2.0 R20 — vision_detections + copilot_sessions + copilot_turns.

Revision ID: 20260710_0014
Revises: 20260710_0013
Create Date: 2026-07-10 11:50:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260710_0014"
down_revision: Union[str, None] = "20260710_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vision_detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("drone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stream_key", sa.String(64), nullable=True),
        sa.Column("label", sa.String(48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", postgresql.JSONB, nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("alt_m", sa.Float(), nullable=True),
        sa.Column("frame_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frame_idx", sa.Integer(), nullable=True),
        sa.Column("model_tag", sa.String(64), nullable=True),
        sa.Column("runtime", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), server_default="new", nullable=False),
        sa.Column("meta", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vd_tenant", "vision_detections", ["tenant_id"])
    op.create_index("ix_vd_drone", "vision_detections", ["drone_id"])
    op.create_index("ix_vd_mission", "vision_detections", ["mission_id"])
    op.create_index("ix_vd_label", "vision_detections", ["label"])
    op.create_index("ix_vd_status", "vision_detections", ["status"])
    op.create_index("ix_vd_created", "vision_detections", ["created_at"])

    op.create_table(
        "copilot_sessions_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(128), server_default="新会话", nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("persona", sa.String(24), server_default="operator", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cs_tenant", "copilot_sessions_v2", ["tenant_id"])
    op.create_index("ix_cs_user", "copilot_sessions_v2", ["user_id"])

    op.create_table(
        "copilot_turns_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("copilot_sessions_v2.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_idx", sa.Integer(), server_default="0", nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(48), nullable=True),
        sa.Column("args", postgresql.JSONB, nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("tool_call", postgresql.JSONB, nullable=True),
        sa.Column("tool_result", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ct_session", "copilot_turns_v2", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_ct_session", table_name="copilot_turns_v2")
    op.drop_table("copilot_turns_v2")
    op.drop_index("ix_cs_user", table_name="copilot_sessions_v2")
    op.drop_index("ix_cs_tenant", table_name="copilot_sessions_v2")
    op.drop_table("copilot_sessions_v2")
    for ix in ("ix_vd_created", "ix_vd_status", "ix_vd_label",
               "ix_vd_mission", "ix_vd_drone", "ix_vd_tenant"):
        op.drop_index(ix, table_name="vision_detections")
    op.drop_table("vision_detections")
