"""E2.4 · Copilot Plan-Execute-Reflect 任务链 (Task Chain).

设计动机
--------
现有两种执行范式各有短板：
- v2.0 CopilotAgent(Function Calling) — LLM 自由发起工具调用，中间没有显式的
  "计划-执行-复盘" 结构，可观察性差；用户看到的只是一堆 tool_use 事件。
- E2.1 WorkflowDSL — 静态 DAG，作者预先写死；无法根据中间结果动态改变后续步骤。

TaskChain 填在两者之间：
1. **Plan**  — LLM 根据用户目标先产出一份显式的 subtask 列表（每条含 title,
    tool, tentative_args, why）。用户/审批人可先看这份计划。
2. **Execute** — 逐条执行，每步产生 `TaskChainStep`（含 args_resolved,
    tool_output, notes）。
3. **Reflect** — 每 K 步或每次失败后，LLM 可以 revise 剩余 subtask（append /
    replace_remaining），把 revision 记为一条 `TaskChainRevision`。

不是 workflow — 生命周期短，与一次对话绑定；退出时不持久 dsl，只保留可
读回放。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotTaskChain(Base):
    """一次 plan-execute-reflect 会话.

    States: draft(计划中) -> running(执行中) -> paused/completed/failed/cancelled
    """

    __tablename__ = "copilot_task_chains"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    owner_user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    goal: Mapped[str] = mapped_column(Text, nullable=False)  # 用户原始目标描述
    plan_json: Mapped[list | dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft",
        server_default=text("'draft'"),
    )  # draft | running | paused | completed | failed | cancelled
    current_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    reflection_notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CopilotTaskChainStep(Base):
    """任务链中一个已执行 (或跳过) 的 subtask."""

    __tablename__ = "copilot_task_chain_steps"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    chain_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    args_planned: Mapped[dict | None] = mapped_column(JSONB)
    args_resolved: Mapped[dict | None] = mapped_column(JSONB)
    output_json: Mapped[dict | list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default=text("'pending'"),
    )  # pending | running | succeeded | failed | skipped
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class CopilotTaskChainRevision(Base):
    """一次 reflection 产生的 plan 变更."""

    __tablename__ = "copilot_task_chain_revisions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    chain_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    at_step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # append_step | replace_remaining | mark_completed | abort
    prev_plan: Mapped[list | dict | None] = mapped_column(JSONB)
    new_plan: Mapped[list | dict | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )


class CopilotTaskChainApproval(Base):
    """审批门控 — 当 step 命中 approval_required 时的挂起记录."""

    __tablename__ = "copilot_task_chain_approvals"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    chain_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    step_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, unique=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), nullable=False)
    required_reason: Mapped[str] = mapped_column(Text, nullable=False)
    args_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default=text("'pending'"),
    )  # pending | approved | rejected | expired
    approver_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    modifications: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


Index(
    "ix_copilot_task_chains_org_status",
    CopilotTaskChain.org_id, CopilotTaskChain.status,
)
