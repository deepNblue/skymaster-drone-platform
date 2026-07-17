"""CopilotMemory — Copilot 长期记忆表 (v2.1 E2.3).

设计权衡:
-----------
不引入 sentence-transformers / pgvector 依赖 —— 当前 backend-v0.1 无 GPU 可用,
且第一版长期记忆的检索规模在几百到几万条,SQL LIKE + tsvector 已足够。若后续
上量,可平滑迁移到 pgvector (只加一列 `embedding VECTOR(384)`)。

记忆分类:
- ``preference``  用户偏好 (如 "巡检默认时长 40 分钟", "偏好使用 Mavic 3E")
- ``fact``        中长期事实 (如 "组织 ID xxx 的辖区包含 3 个 NFZ")
- ``task_history`` 任务历史 (如 "上次巡检 mission_id=... 在 07-15 完成, 用时 22 分钟")
- ``insight``     Agent 自动沉淀的洞察 (由后台 job 从 trace 中提取)

访问权限:
- 默认按 (org_id, user_id) 隔离
- ``scope="org"`` 表示组织内共享 (如"辖区 NFZ 列表"); 组内任意用户可读
- ``scope="user"`` (默认) 仅记忆归属人可读
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotMemory(Base):
    __tablename__ = "copilot_memories"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        # preference | fact | task_history | insight
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user",
        # user | org
    )
    key: Mapped[str | None] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    meta: Mapped[dict | None] = mapped_column(JSONB)

    # Retention hint (in days). 0 or NULL means "keep forever".
    ttl_days: Mapped[int | None] = mapped_column(Integer)

    # Weight used for scoring in search; higher = surface earlier.
    weight: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), index=True
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    source_trace_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), index=True
    )
