"""initial schema — v0.1 core + v2.0 forward-compat placeholders

Revision ID: 20260709_0001
Revises:
Create Date: 2026-07-09

Creates:
  Core (SDD v0.1 §3.1):
    organization, users, drones, missions,
    flight_logs (TimescaleDB hypertable),
    media_assets, audit_logs
  Placeholders (v2.0 forward-compat):
    approval_requests (SDD v2.0-A §3)
    ai_models        (SDD v2.0-B §4)
    copilot_traces   (SDD v2.0-C §5)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260709_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Extensions ---------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # ---- Core tables (SDD v0.1 §3.1) ---------------------------------------
    op.create_table(
        "organization",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "tenant_type",
            sa.String(30),
            nullable=False,
            server_default="standard",
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_pw", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="operator"),
        sa.Column("sso_sub", sa.String(255)),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])

    op.create_table(
        "drones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id"),
        ),
        sa.Column("sn", sa.String(60), nullable=False, unique=True),
        sa.Column("model", sa.String(60)),
        sa.Column("protocol", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default="offline"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_drones_org_id", "drones", ["org_id"])
    op.create_index("ix_drones_status", "drones", ["status"])

    op.create_table(
        "missions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id"),
        ),
        sa.Column(
            "drone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drones.id"),
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("template", sa.String(40)),
        sa.Column("waypoints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("dispatched_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_missions_org_id", "missions", ["org_id"])
    op.create_index("ix_missions_drone_id", "missions", ["drone_id"])
    op.create_index("ix_missions_status", "missions", ["status"])

    # flight_logs — TimescaleDB hypertable, no PK, partitioned on time
    op.create_table(
        "flight_logs",
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("drone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True)),
        sa.Column("lat", sa.Float(precision=53)),
        sa.Column("lng", sa.Float(precision=53)),
        sa.Column("alt", sa.REAL()),
        sa.Column("speed", sa.REAL()),
        sa.Column("heading", sa.REAL()),
        sa.Column("roll", sa.REAL()),
        sa.Column("pitch", sa.REAL()),
        sa.Column("yaw", sa.REAL()),
        sa.Column("battery_pct", sa.REAL()),
        sa.Column("rssi", sa.SmallInteger()),
        sa.Column("gps_sats", sa.SmallInteger()),
        sa.Column("flight_mode", sa.String(20)),
    )
    op.execute(
        "SELECT create_hypertable('flight_logs', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flight_logs_drone_time "
               "ON flight_logs (drone_id, time DESC)")

    op.create_table(
        "media_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id"),
        ),
        sa.Column(
            "drone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drones.id"),
        ),
        sa.Column("type", sa.String(20)),
        sa.Column("minio_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("captured_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_media_assets_mission_id", "media_assets", ["mission_id"])
    op.create_index("ix_media_assets_drone_id", "media_assets", ["drone_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "ts",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("resource", sa.String(120)),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("ip", postgresql.INET()),
        sa.Column("ua", sa.Text()),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_ts", "audit_logs", ["ts"])

    # ---- Placeholder tables — v2.0 forward-compat ---------------------------
    # approval_requests (SDD v2.0-A §3, simplified)
    op.create_table(
        "approval_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True)),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("channel_ref", sa.String(120)),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("submitted_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("approved_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("retries", sa.SmallInteger(), server_default=sa.text("0")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("mission_id", "channel", name="uq_approval_mission_channel"),
    )
    op.create_index(
        "ix_approval_requests_org_status", "approval_requests", ["org_id", "status"]
    )
    op.create_index(
        "ix_approval_requests_channel_submitted",
        "approval_requests",
        ["channel", sa.text("submitted_at DESC")],
    )

    # ai_models (SDD v2.0-B §4)
    op.create_table(
        "ai_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("task_type", sa.String(20), nullable=False),
        sa.Column("triton_model", sa.String(80), nullable=False),
        sa.Column("input_shape", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("minio_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(64)),
        sa.Column("license", sa.String(40), nullable=False),
        sa.Column("price_cent", sa.Integer(), server_default=sa.text("0")),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("deprecated", sa.Boolean(), server_default=sa.text("false")),
    )

    # copilot_traces (SDD v2.0-C §5, simplified — session_id/org_id/user_id
    # kept as loose UUIDs, no FK, because copilot_sessions is deferred to v2.0)
    op.create_table(
        "copilot_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("prompt", sa.Text()),
        sa.Column("intent", sa.String(40)),
        sa.Column("confidence", sa.REAL()),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(20)),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_copilot_traces_session_id", "copilot_traces", ["session_id"])
    op.create_index("ix_copilot_traces_org_id", "copilot_traces", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_copilot_traces_org_id", table_name="copilot_traces")
    op.drop_index("ix_copilot_traces_session_id", table_name="copilot_traces")
    op.drop_table("copilot_traces")

    op.drop_table("ai_models")

    op.drop_index(
        "ix_approval_requests_channel_submitted", table_name="approval_requests"
    )
    op.drop_index("ix_approval_requests_org_status", table_name="approval_requests")
    op.drop_table("approval_requests")

    op.drop_index("ix_audit_logs_ts", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_media_assets_drone_id", table_name="media_assets")
    op.drop_index("ix_media_assets_mission_id", table_name="media_assets")
    op.drop_table("media_assets")

    # flight_logs hypertable — plain DROP TABLE handles it
    op.execute("DROP INDEX IF EXISTS ix_flight_logs_drone_time")
    op.drop_table("flight_logs")

    op.drop_index("ix_missions_status", table_name="missions")
    op.drop_index("ix_missions_drone_id", table_name="missions")
    op.drop_index("ix_missions_org_id", table_name="missions")
    op.drop_table("missions")

    op.drop_index("ix_drones_status", table_name="drones")
    op.drop_index("ix_drones_org_id", table_name="drones")
    op.drop_table("drones")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_table("users")

    op.drop_table("organization")
