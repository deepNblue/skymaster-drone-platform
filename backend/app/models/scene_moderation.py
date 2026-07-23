"""Scene marketplace moderation reports & appeals — v2.1 T2.2.

Adds two new tables on top of T2.0/T2.1:

* ``scene_listing_reports`` — any authenticated user can file a report
  against a listing. Categories align with common content-policy taxonomies
  (copyright / privacy / sensitive_area / illegal / other). Admins process
  the queue via aggregated views.

* ``scene_listing_appeals`` — if a listing is removed by an admin, the
  publisher can file exactly one appeal per moderation event asking for
  review. Admins can accept (restore listing → active) or reject (keeps
  removed).

Design principles
-----------------
* **One report per user per listing** — deduplicate spam. Reopening the
  same complaint updates the row instead of creating dupes.
* **Report is bound to listing, not to specific mod-action** — a listing
  can accumulate reports over its whole lifetime. When admin resolves,
  the report row records the outcome + resolver.
* **Appeals are bound to a specific moderation event** — via a natural key
  (listing_id, appeal_seq). This lets the same listing be removed →
  appealed → restored → removed again → appealed again without collisions.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

REPORT_CATEGORIES: tuple[str, ...] = (
    "copyright",       # 版权侵权
    "privacy",         # 隐私（人脸、车牌、住宅）
    "sensitive_area",  # 敏感区域（军事、边境、核电、要害机关）
    "illegal",         # 违法内容
    "spam",            # 垃圾/低质量
    "other",
)

REPORT_STATUSES: tuple[str, ...] = (
    "open",       # 新建，未处理
    "reviewing",  # admin claim 处理中
    "accepted",   # admin 认为举报成立 → 触发 moderate
    "rejected",   # admin 认为举报不成立
    "duplicate",  # 已有其它报告覆盖
)

APPEAL_STATUSES: tuple[str, ...] = (
    "pending",   # 等待复核
    "accepted",  # admin 同意申诉 → 恢复 listing
    "rejected",  # admin 维持原判
    "withdrawn", # 作者主动撤销
)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class SceneListingReport(Base):
    __tablename__ = "scene_listing_reports"
    __table_args__ = (
        UniqueConstraint(
            "listing_id", "reporter_user_id",
            name="uq_scene_listing_report_dedupe",
        ),
        CheckConstraint(
            "category IN ('copyright','privacy','sensitive_area','illegal','spam','other')",
            name="ck_scene_listing_report_category",
        ),
        CheckConstraint(
            "status IN ('open','reviewing','accepted','rejected','duplicate')",
            name="ck_scene_listing_report_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scene_listings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reporter_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    reporter_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="open", default="open", index=True,
    )
    resolver_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


class SceneListingAppeal(Base):
    __tablename__ = "scene_listing_appeals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','rejected','withdrawn')",
            name="ck_scene_listing_appeal_status",
        ),
        UniqueConstraint(
            "listing_id", "appeal_seq",
            name="uq_scene_listing_appeal_seq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scene_listings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Sequence number scoped to the listing so re-appealed listings don't clash.
    appeal_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    appellant_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Snapshot of moderation context at appeal time.
    original_status: Mapped[str] = mapped_column(String(16), nullable=False)
    original_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", default="pending", index=True,
    )
    resolver_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )
