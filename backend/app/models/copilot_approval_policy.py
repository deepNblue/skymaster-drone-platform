"""CopilotApprovalPolicy — 组织级双签/多签审批策略 (v2.1 E2.5).

设计意图:
-----------
v2.0 的 CopilotApproval 是"单人审批 + 结论字段"的极简 schema。v2.1 E2.5 让
一个 tool call 可能需要 ≥ 2 人签核（例如"批量删除机型" 需要合规官 + 运维总监同签），
且不同工具/风险等级/触发场景走不同审批链。

我们不改现有 CopilotApproval 表（保持向后兼容），而是新增两张表:
- CopilotApprovalPolicy: 每 org 一份的策略（哪些 tool 需要几签）
- CopilotApprovalSignoff: 一次审批的多个签核记录

Approval 网关的决策流程 (伪代码):

    if tool in policy.allowlist_single:
        need = 1
    elif tool matches policy.dual_sign_rule:
        need = 2
    elif risk_level >= policy.dual_sign_min_risk:
        need = 2
    else:
        need = 1

    if all(sig.decision == 'approve' for sig in signoffs) and len(signoffs) >= need:
        approve
    elif any(sig.decision == 'reject' for sig in signoffs):
        reject immediately

策略字段:
- ``dual_sign_tools``: list[str] — 明确要求双签的工具名
- ``dual_sign_min_risk``: {"low"|"medium"|"high"|"critical"} — 达到该风险自动升级双签
- ``dual_sign_min_role_levels``: [levelA, levelB] — 双签角色矩阵（如 admin+compliance）
- ``dual_sign_bypass_roles``: [role] — 拥有此角色的用户可以单签通过（如 superadmin）
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotApprovalPolicy(Base):
    __tablename__ = "copilot_approval_policies"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, unique=True, index=True
    )

    # Tools that always require dual sign.
    dual_sign_tools: Mapped[list[str] | None] = mapped_column(JSONB)

    # Minimum risk that auto-escalates to dual sign.
    #   None = never auto-escalate; "high"/"critical" typical.
    dual_sign_min_risk: Mapped[str | None] = mapped_column(String(16))

    # Required approver roles (both must be represented among signoffs).
    # Example: ["admin", "compliance_officer"]
    required_roles: Mapped[list[str] | None] = mapped_column(JSONB)

    # Roles whose single approval is enough regardless of dual-sign rules.
    bypass_roles: Mapped[list[str] | None] = mapped_column(JSONB)

    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


class CopilotApprovalSignoff(Base):
    __tablename__ = "copilot_approval_signoffs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    approval_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    signer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    signer_role: Mapped[str | None] = mapped_column(String(60))
    decision: Mapped[str] = mapped_column(
        String(16), nullable=False  # approve | reject
    )
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
