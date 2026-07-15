"""AI Model Marketplace models — v2.0 Track E.

Design goals
------------

* **Multi-tenant catalog** — 每个租户既是消费方也可以是提供方；模型有
  `visibility=public|private|org` 三层可见性。
* **版本化** — 一个 ``ModelListing`` 可挂多个 ``ModelVersion``；生产
  部署总是绑定到某个具体版本（不可变哈希 = 供审计追溯）。
* **计量** — ``ModelDeployment`` 记录租户实际部署，``ModelUsageEvent``
  按调用 / 帧 / token 累积用量，供后续计费或配额限流。
* **审核** — 上传的模型 artifact 需要经过 ``review_status``；平台方
  可拒绝，被拒绝的版本不能被部署。

Deliberately *not* included in this skeleton:
* 真实模型 artifact 存储（S3/MinIO）  ← Track E-2
* GPU 资源调度                        ← Track E-3
* 端到端计费网关                      ← Track E-4

只做「元数据 + 生命周期状态机」，后续 workstream 挂在上面。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModelListing(Base):
    """A listing = a "product page" for a model family (e.g. YOLO-v8-drone)."""

    __tablename__ = "model_listings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #  ^ detection / classification / segmentation / tracking / vlm / llm / audio ...
    framework: Mapped[str] = mapped_column(String(32), nullable=False)
    #  ^ pytorch / onnx / tensorrt / openvino / paddle ...
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="public", index=True,
    )  # public / private / org
    owner_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    license: Mapped[str] = mapped_column(String(32), nullable=False, server_default="proprietary")
    #  ^ mit / apache-2 / cc-by-nc / proprietary / gpl-v3 ...
    price_model: Mapped[str] = mapped_column(String(16), nullable=False, server_default="free")
    #  ^ free / per_call / per_frame / per_token / per_month
    price_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="CNY")
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class ModelVersion(Base):
    """One shippable version of a listing — points to an artifact URI + hash."""

    __tablename__ = "model_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)  # semver-ish
    artifact_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inputs_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outputs_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #  ^ 用于 UI 自动生成推理表单
    hardware: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #  ^ ["cuda>=11.8", "vram>=8gb"] etc — surface to marketplace filter
    benchmark: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #  ^ {"mAP@0.5": 0.72, "fps_rtx4090": 120, "latency_ms": 8.3}
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", index=True,
    )  # pending / approved / rejected / withdrawn
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ModelDeployment(Base):
    """A tenant "installs" a specific version — used for quota + routing."""

    __tablename__ = "model_deployments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="installed", index=True,
    )  # installed / active / suspended / uninstalled
    endpoint_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    quota_calls_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class ModelUsageEvent(Base):
    """Append-only usage log — one row per API call / batch."""

    __tablename__ = "model_usage_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    deployment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    #  ^ call = 1 unit; frame = frame count; token = token count
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    #  ^ call / frame / token
    latency_ms: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ok")
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )


# ---------------------------------------------------------------------------
# T5.10 — favorites (user-scoped bookmarks)
# ---------------------------------------------------------------------------
class ModelFavorite(Base):
    """User bookmarks a listing for later. UI-only signal — favorites
    don't affect quotas or routing.

    Idempotent by unique(user_id, listing_id): starring twice is a no-op.
    """

    __tablename__ = "model_favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_model_fav_uniq"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
