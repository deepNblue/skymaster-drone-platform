"""E2.4 · Task Chain service (plan-execute-reflect loop).

核心不变式
--------
1. **plan_json 是 subtask list**: 每条 subtask = {title, tool, args, why?, done?}
2. **step_index 单调递增，与 plan_json 索引对齐**: 允许 revision 修改 plan，但
   已完成的前缀不变（`prev_plan` 保留原样，`new_plan` 仅覆盖 tail）
3. **reflection 只能改未来**: `at_step_index >= current_index`，不能改历史
4. **每步落库**: 每个 `advance_step` 完成后立即 commit，crash-safe
5. **审批集成**: 若 tool 命中 CopilotApprovalPolicy 或 CopilotToolPolicy 的
   `deny/manual_approval`，step 落库为 status=paused + error=待审批，chain
   status=paused，等待外部审批完成后手动 `resume`
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_task_chain import (
    CopilotTaskChain,
    CopilotTaskChainApproval,
    CopilotTaskChainRevision,
    CopilotTaskChainStep,
)
from app.services import copilot_tool_policy as policy_svc
from app.services.tool_registry import ToolContext, ToolRegistry


class TaskChainError(RuntimeError):
    pass


VALID_STATUSES = {"draft", "running", "paused", "completed", "failed", "cancelled"}
VALID_STEP_STATUSES = {"pending", "running", "succeeded", "failed", "skipped", "paused"}


@dataclass
class Subtask:
    title: str
    tool: str
    args: dict[str, Any]
    why: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Subtask":
        try:
            return cls(
                title=str(d["title"]),
                tool=str(d["tool"]),
                args=dict(d.get("args") or {}),
                why=str(d.get("why") or ""),
            )
        except (KeyError, TypeError) as e:
            raise TaskChainError(f"invalid subtask: {d!r}: {e}")

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "tool": self.tool, "args": self.args, "why": self.why}


def _validate_plan(plan: list[dict[str, Any]], registry: ToolRegistry) -> list[Subtask]:
    if not isinstance(plan, list) or not plan:
        raise TaskChainError("plan must be a non-empty list")
    if len(plan) > 32:
        raise TaskChainError("plan too long (max 32 subtasks)")
    parsed: list[Subtask] = []
    known = set(registry.names())
    for i, item in enumerate(plan):
        st = Subtask.from_dict(item)
        if st.tool not in known:
            raise TaskChainError(f"subtask[{i}] uses unknown tool: {st.tool}")
        parsed.append(st)
    return parsed


# ------------------------------------------------------------------
# Create / read
# ------------------------------------------------------------------
async def create_chain(
    db: AsyncSession,
    *,
    owner_user_id: UUID,
    org_id: UUID | None,
    goal: str,
    plan: list[dict[str, Any]],
    registry: ToolRegistry,
    conversation_id: UUID | None = None,
) -> CopilotTaskChain:
    _validate_plan(plan, registry)
    chain = CopilotTaskChain(
        id=uuid4(),
        org_id=org_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        goal=goal,
        plan_json=plan,
        status="draft",
        current_index=0,
    )
    db.add(chain)
    await db.commit()
    await db.refresh(chain)
    return chain


async def get_chain(
    db: AsyncSession, *, chain_id: UUID, viewer_org_id: UUID | None,
) -> CopilotTaskChain:
    res = await db.execute(
        select(CopilotTaskChain).where(CopilotTaskChain.id == chain_id)
    )
    chain = res.scalar_one_or_none()
    if chain is None:
        raise TaskChainError("chain not found")
    if chain.org_id != viewer_org_id:
        raise TaskChainError("chain not accessible")
    return chain


async def list_chains(
    db: AsyncSession, *, org_id: UUID | None,
    status: str | None = None, limit: int = 50,
) -> list[CopilotTaskChain]:
    stmt = select(CopilotTaskChain).where(CopilotTaskChain.org_id == org_id)
    if status:
        if status not in VALID_STATUSES:
            raise TaskChainError(f"invalid status filter: {status}")
        stmt = stmt.where(CopilotTaskChain.status == status)
    stmt = stmt.order_by(CopilotTaskChain.updated_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars())


async def list_steps(
    db: AsyncSession, *, chain_id: UUID,
) -> list[CopilotTaskChainStep]:
    res = await db.execute(
        select(CopilotTaskChainStep)
        .where(CopilotTaskChainStep.chain_id == chain_id)
        .order_by(CopilotTaskChainStep.step_index.asc())
    )
    return list(res.scalars())


async def list_revisions(
    db: AsyncSession, *, chain_id: UUID,
) -> list[CopilotTaskChainRevision]:
    res = await db.execute(
        select(CopilotTaskChainRevision)
        .where(CopilotTaskChainRevision.chain_id == chain_id)
        .order_by(CopilotTaskChainRevision.created_at.asc())
    )
    return list(res.scalars())


# ------------------------------------------------------------------
# Execute
# ------------------------------------------------------------------
@dataclass
class StepResult:
    step: CopilotTaskChainStep
    chain: CopilotTaskChain


async def advance_step(
    db: AsyncSession,
    *,
    chain_id: UUID,
    executor_user_id: UUID,
    executor_org_id: UUID | None,
    registry: ToolRegistry,
    tool_ctx_factory,  # (chain) -> ToolContext
) -> StepResult:
    chain = await get_chain(db, chain_id=chain_id, viewer_org_id=executor_org_id)
    if chain.status in ("completed", "failed", "cancelled"):
        raise TaskChainError(f"chain is {chain.status}, cannot advance")
    if chain.owner_user_id != executor_user_id:
        raise TaskChainError("only chain owner can advance")

    plan = list(chain.plan_json or [])
    idx = chain.current_index
    if idx >= len(plan):
        # Nothing left
        chain.status = "completed"
        chain.completed_at = datetime.now(timezone.utc)
        chain.updated_at = datetime.now(timezone.utc)
        await db.commit()
        raise TaskChainError("chain already finished")

    st = Subtask.from_dict(plan[idx])

    if chain.status == "draft":
        chain.status = "running"

    # -- Policy gate: consult copilot_tool_policy before running ---------
    # If an APPROVED approval already exists for this (chain, step_index),
    # this run is a resume — bypass the policy check.
    resume_ok = False
    approved_check = await db.execute(
        select(CopilotTaskChainApproval).where(
            CopilotTaskChainApproval.chain_id == chain.id,
            CopilotTaskChainApproval.step_index == idx,
            CopilotTaskChainApproval.status == "approved",
        )
    )
    if approved_check.scalar_one_or_none() is not None:
        resume_ok = True

    decision = None
    if not resume_ok and (chain.org_id or executor_org_id):
        decision = await policy_svc.evaluate(
            db,
            org_id=chain.org_id or executor_org_id,
            tool_name=st.tool,
        )

    if decision is not None and decision.action == "blocked":
        # Hard block — do not create step, mark chain failed
        chain.status = "failed"
        chain.error = f"tool {st.tool} blocked by policy: {decision.reason}"
        chain.updated_at = datetime.now(timezone.utc)
        await db.commit()
        raise TaskChainError(chain.error)

    step_row = CopilotTaskChainStep(
        id=uuid4(),
        chain_id=chain.id,
        step_index=idx,
        title=st.title,
        tool=st.tool,
        args_planned=st.args,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(step_row)
    await db.flush()  # get the row ID

    # Substitute ${steps.N.output.x} references from prior step outputs
    args_resolved = _resolve_args(st.args, prior_steps=await list_steps(db, chain_id=chain.id))
    step_row.args_resolved = args_resolved

    # -- Approval required? pause chain & write approval row -----------
    if decision is not None and decision.action == "approval_required":
        step_row.status = "paused"
        step_row.error = f"approval required: {decision.reason}"
        step_row.finished_at = datetime.now(timezone.utc)
        chain.status = "paused"
        chain.error = None
        approval = CopilotTaskChainApproval(
            id=uuid4(),
            chain_id=chain.id,
            step_id=step_row.id,
            step_index=idx,
            tool_name=st.tool,
            risk_level=decision.risk_level,
            permission=decision.permission,
            required_reason=decision.reason or "policy requires approval",
            args_snapshot=args_resolved,
            status="pending",
        )
        db.add(approval)
        chain.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(chain)
        await db.refresh(step_row)
        return StepResult(step=step_row, chain=chain)

    ctx = tool_ctx_factory(chain)
    try:
        out = await registry.call(st.tool, args_resolved, ctx)
        step_row.output_json = out
        step_row.status = "succeeded"
        step_row.finished_at = datetime.now(timezone.utc)
        chain.current_index = idx + 1
        if chain.current_index >= len(plan):
            chain.status = "completed"
            chain.completed_at = datetime.now(timezone.utc)
    except Exception as e:  # noqa: BLE001
        step_row.status = "failed"
        step_row.error = f"{type(e).__name__}: {e}"
        step_row.finished_at = datetime.now(timezone.utc)
        chain.status = "failed"
        chain.error = step_row.error
    finally:
        chain.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(chain)
        await db.refresh(step_row)

    # -- E2.6: writeback to conversation memory once chain is terminal --
    if chain.status in ("completed", "failed"):
        try:
            await _writeback_task_history(db, chain=chain)
        except Exception:  # noqa: BLE001
            # writeback is best-effort; never break the caller
            pass

    return StepResult(step=step_row, chain=chain)


async def run_to_end(
    db: AsyncSession,
    *,
    chain_id: UUID,
    executor_user_id: UUID,
    executor_org_id: UUID | None,
    registry: ToolRegistry,
    tool_ctx_factory,
    max_steps: int = 32,
) -> CopilotTaskChain:
    """Loop advance_step until chain terminates or max_steps reached."""
    chain = await get_chain(db, chain_id=chain_id, viewer_org_id=executor_org_id)
    steps_run = 0
    while chain.status in ("draft", "running") and steps_run < max_steps:
        try:
            r = await advance_step(
                db, chain_id=chain_id,
                executor_user_id=executor_user_id,
                executor_org_id=executor_org_id,
                registry=registry, tool_ctx_factory=tool_ctx_factory,
            )
            chain = r.chain
            steps_run += 1
            # Stop if paused (awaiting approval), failed, completed, or cancelled
            if chain.status not in ("running", "draft"):
                break
        except TaskChainError:
            break
    return chain


# ------------------------------------------------------------------
# Reflect / revise
# ------------------------------------------------------------------
async def revise_plan(
    db: AsyncSession,
    *,
    chain_id: UUID,
    actor_user_id: UUID,
    actor_org_id: UUID | None,
    kind: str,
    new_tail: list[dict[str, Any]] | None,
    reason: str,
    registry: ToolRegistry,
) -> CopilotTaskChainRevision:
    """Kinds:
      - append_step: new_tail is a list of subtasks appended after current plan
      - replace_remaining: new_tail replaces plan[current_index:]
      - mark_completed: no new_tail; force chain to completed
      - abort: force chain to cancelled
    """
    chain = await get_chain(db, chain_id=chain_id, viewer_org_id=actor_org_id)
    if chain.owner_user_id != actor_user_id:
        raise TaskChainError("only owner can revise")
    if chain.status in ("completed", "cancelled"):
        raise TaskChainError(f"cannot revise a {chain.status} chain")

    prev_plan = list(chain.plan_json or [])
    new_plan: list[dict[str, Any]] = prev_plan
    if kind == "append_step":
        if not new_tail:
            raise TaskChainError("append_step requires new_tail")
        _validate_plan(new_tail, registry)
        new_plan = prev_plan + [Subtask.from_dict(x).to_dict() for x in new_tail]
    elif kind == "replace_remaining":
        if new_tail is None:
            raise TaskChainError("replace_remaining requires new_tail (may be empty)")
        head = prev_plan[: chain.current_index]
        tail = [Subtask.from_dict(x).to_dict() for x in new_tail]
        combined = head + tail
        if combined:
            _validate_plan(combined, registry)
        new_plan = combined
    elif kind == "mark_completed":
        chain.status = "completed"
        chain.completed_at = datetime.now(timezone.utc)
    elif kind == "abort":
        chain.status = "cancelled"
    else:
        raise TaskChainError(f"unknown revision kind: {kind}")

    chain.plan_json = new_plan
    chain.updated_at = datetime.now(timezone.utc)

    rev = CopilotTaskChainRevision(
        id=uuid4(),
        chain_id=chain.id,
        at_step_index=chain.current_index,
        kind=kind,
        prev_plan=prev_plan,
        new_plan=new_plan,
        reason=reason,
    )
    db.add(rev)
    await db.commit()
    await db.refresh(rev)
    return rev


async def cancel_chain(
    db: AsyncSession, *, chain_id: UUID,
    actor_user_id: UUID, actor_org_id: UUID | None,
) -> CopilotTaskChain:
    chain = await get_chain(db, chain_id=chain_id, viewer_org_id=actor_org_id)
    if chain.owner_user_id != actor_user_id:
        raise TaskChainError("only owner can cancel")
    if chain.status in ("completed", "cancelled", "failed"):
        return chain
    chain.status = "cancelled"
    chain.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(chain)
    try:
        await _writeback_task_history(db, chain=chain)
    except Exception:  # noqa: BLE001
        pass
    return chain


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _resolve_args(
    args: dict[str, Any], *, prior_steps: list[CopilotTaskChainStep],
) -> dict[str, Any]:
    """Replace ${steps.N.output.key.subkey} references in args.

    Only string leaves; ints/bools/lists pass through untouched.
    Missing refs → substitute empty string (never raise here, tool will fail
    louder with clearer args).
    """
    import re
    outputs_by_idx: dict[int, Any] = {
        s.step_index: s.output_json for s in prior_steps if s.output_json is not None
    }

    ref_re = re.compile(r"\$\{steps\.(\d+)\.output((?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\}")

    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            def sub(m: re.Match[str]) -> str:
                idx = int(m.group(1))
                path = [p for p in m.group(2).split(".") if p]
                node = outputs_by_idx.get(idx)
                for p in path:
                    if isinstance(node, dict) and p in node:
                        node = node[p]
                    else:
                        return ""
                return str(node) if node is not None else ""
            return ref_re.sub(sub, v)
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        return v

    return _walk(args)


def chain_to_dict(chain: CopilotTaskChain) -> dict[str, Any]:
    return {
        "id": str(chain.id),
        "org_id": str(chain.org_id) if chain.org_id else None,
        "owner_user_id": str(chain.owner_user_id),
        "conversation_id": str(chain.conversation_id) if chain.conversation_id else None,
        "goal": chain.goal,
        "plan_json": chain.plan_json,
        "status": chain.status,
        "current_index": chain.current_index,
        "reflection_notes": chain.reflection_notes,
        "error": chain.error,
        "created_at": chain.created_at.isoformat() if chain.created_at else None,
        "updated_at": chain.updated_at.isoformat() if chain.updated_at else None,
        "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
    }


def step_to_dict(row: CopilotTaskChainStep) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "chain_id": str(row.chain_id),
        "step_index": row.step_index,
        "title": row.title,
        "tool": row.tool,
        "args_planned": row.args_planned,
        "args_resolved": row.args_resolved,
        "output_json": row.output_json,
        "status": row.status,
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def revision_to_dict(row: CopilotTaskChainRevision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "chain_id": str(row.chain_id),
        "at_step_index": row.at_step_index,
        "kind": row.kind,
        "prev_plan": row.prev_plan,
        "new_plan": row.new_plan,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ------------------------------------------------------------------
# E2.6 · Writeback to conversation memory
# ------------------------------------------------------------------
async def _writeback_task_history(
    db: AsyncSession, *, chain: CopilotTaskChain,
) -> None:
    """Summarise a terminal chain and persist as a `task_history` memory.

    Best-effort: never raises. Downstream conversation UIs can retrieve
    this via the existing copilot_memory search — no extra table needed.
    """
    if chain.org_id is None or chain.owner_user_id is None:
        return
    steps = await list_steps(db, chain_id=chain.id)

    plan = chain.plan_json or []
    step_lines = []
    for i, st in enumerate(plan):
        step = next((s for s in steps if s.step_index == i), None)
        marker = "•"
        if step is not None:
            marker = {
                "succeeded": "✓", "failed": "✗",
                "paused": "⏸", "pending": "•", "running": "…",
            }.get(step.status, "•")
        tool = (st or {}).get("tool", "?")
        title = (st or {}).get("title", "")
        step_lines.append(f"{marker} #{i + 1} {tool} · {title}")

    summary_lines = [
        f"目标: {chain.goal}",
        f"状态: {chain.status}",
    ]
    if chain.error:
        summary_lines.append(f"错误: {chain.error}")
    summary_lines.append("步骤:")
    summary_lines.extend(step_lines)

    from app.services import copilot_memory as memory_svc
    await memory_svc.create_memory(
        db,
        org_id=chain.org_id,
        user_id=chain.owner_user_id,
        kind="task_history",
        scope="user",
        # key stabilises upsert — one memory per chain
        key=f"task_chain:{chain.id}",
        content="\n".join(summary_lines),
        tags=["task_chain", chain.status],
        meta={
            "chain_id": str(chain.id),
            "goal": chain.goal,
            "status": chain.status,
            "conversation_id": (
                str(chain.conversation_id) if chain.conversation_id else None
            ),
            "step_count": len(plan),
        },
        weight=60 if chain.status == "completed" else 45,
    )


# ------------------------------------------------------------------
# Approval integration
# ------------------------------------------------------------------
def approval_to_dict(row: CopilotTaskChainApproval) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "chain_id": str(row.chain_id),
        "step_id": str(row.step_id),
        "step_index": row.step_index,
        "tool_name": row.tool_name,
        "risk_level": row.risk_level,
        "permission": row.permission,
        "required_reason": row.required_reason,
        "args_snapshot": row.args_snapshot,
        "status": row.status,
        "approver_id": str(row.approver_id) if row.approver_id else None,
        "decision_reason": row.decision_reason,
        "modifications": row.modifications,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


async def list_approvals(
    db: AsyncSession, *, chain_id: UUID,
) -> list[CopilotTaskChainApproval]:
    res = await db.execute(
        select(CopilotTaskChainApproval)
        .where(CopilotTaskChainApproval.chain_id == chain_id)
        .order_by(CopilotTaskChainApproval.created_at.asc())
    )
    return list(res.scalars())


async def list_pending_approvals_for_org(
    db: AsyncSession, *, org_id: UUID | None, limit: int = 50,
) -> list[tuple[CopilotTaskChainApproval, CopilotTaskChain]]:
    """Approvals awaiting decision, scoped to the caller's org."""
    stmt = (
        select(CopilotTaskChainApproval, CopilotTaskChain)
        .join(
            CopilotTaskChain,
            CopilotTaskChain.id == CopilotTaskChainApproval.chain_id,
        )
        .where(
            CopilotTaskChain.org_id == org_id,
            CopilotTaskChainApproval.status == "pending",
        )
        .order_by(CopilotTaskChainApproval.created_at.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.all())


async def decide_approval(
    db: AsyncSession,
    *,
    approval_id: UUID,
    approver_id: UUID,
    approver_org_id: UUID | None,
    decision: str,  # "approved" | "rejected"
    decision_reason: str,
    modifications: dict[str, Any] | None = None,
) -> CopilotTaskChainApproval:
    if decision not in ("approved", "rejected"):
        raise TaskChainError(f"invalid decision: {decision}")

    res = await db.execute(
        select(CopilotTaskChainApproval).where(
            CopilotTaskChainApproval.id == approval_id
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise TaskChainError("approval not found")
    if row.status != "pending":
        raise TaskChainError(f"approval already {row.status}")

    # Verify chain belongs to approver's org
    chain = await get_chain(db, chain_id=row.chain_id, viewer_org_id=approver_org_id)

    row.status = decision
    row.approver_id = approver_id
    row.decision_reason = decision_reason
    row.modifications = modifications
    row.decided_at = datetime.now(timezone.utc)

    # Update the paused step accordingly
    step_res = await db.execute(
        select(CopilotTaskChainStep).where(CopilotTaskChainStep.id == row.step_id)
    )
    step = step_res.scalar_one_or_none()
    if step is not None:
        if decision == "rejected":
            step.status = "failed"
            step.error = f"rejected by approver: {decision_reason}"
            step.finished_at = datetime.now(timezone.utc)
            chain.status = "failed"
            chain.error = step.error
        else:
            # Approved — reset step to pending so next advance can re-run it
            step.status = "pending"
            step.error = None
            step.started_at = None
            step.finished_at = None
            if modifications:
                # Persist any tweaks to args before re-run
                step.args_planned = modifications
                # keep plan_json in sync with mods for step visibility
                plan = list(chain.plan_json or [])
                if 0 <= row.step_index < len(plan):
                    entry = dict(plan[row.step_index])
                    entry["args"] = modifications
                    plan[row.step_index] = entry
                    chain.plan_json = plan
            chain.status = "running"
            chain.error = None

    chain.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    if decision == "rejected":
        try:
            await _writeback_task_history(db, chain=chain)
        except Exception:  # noqa: BLE001
            pass
    return row


async def resume_after_approval(
    db: AsyncSession,
    *,
    chain_id: UUID,
    executor_user_id: UUID,
    executor_org_id: UUID | None,
    registry: ToolRegistry,
    tool_ctx_factory,
) -> StepResult | None:
    """After an approval is granted, delete the paused step and advance.

    Returns None if chain is no longer resumable (e.g. rejected → failed).
    """
    chain = await get_chain(db, chain_id=chain_id, viewer_org_id=executor_org_id)
    if chain.status != "running":
        # e.g. rejected already flipped it to "failed"
        return None
    # Drop the paused step so advance_step re-creates it
    steps_res = await db.execute(
        select(CopilotTaskChainStep).where(
            CopilotTaskChainStep.chain_id == chain_id,
            CopilotTaskChainStep.step_index == chain.current_index,
            CopilotTaskChainStep.status.in_(("pending", "paused")),
        )
    )
    for existing in steps_res.scalars():
        await db.delete(existing)
    await db.commit()

    return await advance_step(
        db, chain_id=chain_id,
        executor_user_id=executor_user_id,
        executor_org_id=executor_org_id,
        registry=registry, tool_ctx_factory=tool_ctx_factory,
    )
