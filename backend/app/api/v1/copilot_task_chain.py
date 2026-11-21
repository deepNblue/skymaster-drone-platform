"""API: /copilot/task-chains — E2.4 plan-execute-reflect."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import copilot_task_chain as svc
from app.services import copilot_task_chain_planner as planner_svc
from app.services.llm_client import LLMClient
from app.services.tool_registry import ToolContext, build_default_registry


router = APIRouter(prefix="/copilot/task-chains", tags=["copilot-task-chains"])


class CreateChainIn(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2048)
    plan: list[dict[str, Any]] = Field(..., min_length=1, max_length=32)
    conversation_id: UUID | None = None


class ReviseIn(BaseModel):
    kind: str = Field(..., pattern=r"^(append_step|replace_remaining|mark_completed|abort)$")
    new_tail: list[dict[str, Any]] | None = None
    reason: str = Field(..., min_length=1, max_length=1024)


class PlanIn(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2048)


class AutoCreateIn(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2048)
    conversation_id: UUID | None = None


class ReflectIn(BaseModel):
    trigger: str = Field("user_reflect", pattern=r"^(step_failed|user_reflect|off_track)$")
    apply: bool = True  # if True, apply the suggested revision immediately


def _build_llm() -> LLMClient:
    return LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        protocol=settings.llm_protocol,
    )


def _ctx_factory(db: AsyncSession, user: User):
    def _f(chain):
        return ToolContext(db=db, org_id=user.org_id, user_id=user.id)
    return _f


@router.post("", response_model=dict[str, Any])
async def api_create(
    body: CreateChainIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    reg = build_default_registry()
    try:
        chain = await svc.create_chain(
            db, owner_user_id=user.id, org_id=user.org_id,
            goal=body.goal, plan=body.plan, registry=reg,
            conversation_id=body.conversation_id,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return svc.chain_to_dict(chain)


@router.post("/plan", response_model=dict[str, Any])
async def api_plan(
    body: PlanIn,
    user: User = Depends(get_current_user),  # noqa: ARG001 (auth-gate only)
) -> dict[str, Any]:
    """Dry-run: ask the LLM to draft a plan; return it without persisting."""
    reg = build_default_registry()
    llm = _build_llm()
    try:
        result = await planner_svc.plan(goal=body.goal, llm=llm, registry=reg)
    except planner_svc.PlannerError as e:
        raise HTTPException(400, f"planner error: {e}")
    return {"goal": body.goal, "plan": result.subtasks}


@router.post("/auto", response_model=dict[str, Any])
async def api_auto_create(
    body: AutoCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Plan-and-create in one shot: LLM produces plan, we persist as chain."""
    reg = build_default_registry()
    llm = _build_llm()
    try:
        planned = await planner_svc.plan(goal=body.goal, llm=llm, registry=reg)
        chain = await svc.create_chain(
            db, owner_user_id=user.id, org_id=user.org_id,
            goal=body.goal, plan=planned.subtasks, registry=reg,
            conversation_id=body.conversation_id,
        )
    except planner_svc.PlannerError as e:
        raise HTTPException(400, f"planner error: {e}")
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return svc.chain_to_dict(chain)


@router.get("", response_model=dict[str, Any])
async def api_list(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        rows = await svc.list_chains(
            db, org_id=user.org_id, status=status, limit=limit,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return {"items": [svc.chain_to_dict(r) for r in rows]}


@router.get("/{chain_id}", response_model=dict[str, Any])
async def api_get(
    chain_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        chain = await svc.get_chain(db, chain_id=chain_id, viewer_org_id=user.org_id)
    except svc.TaskChainError as e:
        raise HTTPException(404, str(e))
    steps = await svc.list_steps(db, chain_id=chain_id)
    revs = await svc.list_revisions(db, chain_id=chain_id)
    return {
        "chain": svc.chain_to_dict(chain),
        "steps": [svc.step_to_dict(s) for s in steps],
        "revisions": [svc.revision_to_dict(r) for r in revs],
    }


@router.post("/{chain_id}/advance", response_model=dict[str, Any])
async def api_advance(
    chain_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    reg = build_default_registry()
    try:
        r = await svc.advance_step(
            db, chain_id=chain_id,
            executor_user_id=user.id, executor_org_id=user.org_id,
            registry=reg, tool_ctx_factory=_ctx_factory(db, user),
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return {
        "step": svc.step_to_dict(r.step),
        "chain": svc.chain_to_dict(r.chain),
    }


@router.post("/{chain_id}/run", response_model=dict[str, Any])
async def api_run(
    chain_id: UUID,
    max_steps: int = Query(32, ge=1, le=32),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    reg = build_default_registry()
    try:
        chain = await svc.run_to_end(
            db, chain_id=chain_id,
            executor_user_id=user.id, executor_org_id=user.org_id,
            registry=reg, tool_ctx_factory=_ctx_factory(db, user),
            max_steps=max_steps,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    steps = await svc.list_steps(db, chain_id=chain_id)
    return {
        "chain": svc.chain_to_dict(chain),
        "steps": [svc.step_to_dict(s) for s in steps],
    }


@router.post("/{chain_id}/revise", response_model=dict[str, Any])
async def api_revise(
    chain_id: UUID, body: ReviseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    reg = build_default_registry()
    try:
        rev = await svc.revise_plan(
            db, chain_id=chain_id,
            actor_user_id=user.id, actor_org_id=user.org_id,
            kind=body.kind, new_tail=body.new_tail, reason=body.reason,
            registry=reg,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return svc.revision_to_dict(rev)


@router.post("/{chain_id}/reflect", response_model=dict[str, Any])
async def api_reflect(
    chain_id: UUID, body: ReflectIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ask the LLM how to revise the plan and (optionally) apply it."""
    reg = build_default_registry()
    llm = _build_llm()
    try:
        chain = await svc.get_chain(
            db, chain_id=chain_id, viewer_org_id=user.org_id,
        )
        if chain.owner_user_id != user.id:
            raise HTTPException(403, "only owner can reflect")
        steps = await svc.list_steps(db, chain_id=chain_id)
        summary = planner_svc.summarize_steps(steps)
        suggestion = await planner_svc.reflect(
            goal=chain.goal, plan_json=list(chain.plan_json or []),
            steps_summary=summary, trigger=body.trigger,
            llm=llm, registry=reg,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    except planner_svc.PlannerError as e:
        raise HTTPException(400, f"reflector error: {e}")

    payload: dict[str, Any] = {
        "suggestion": {
            "kind": suggestion.kind,
            "new_tail": suggestion.new_tail,
            "reason": suggestion.reason,
        },
    }
    if body.apply:
        try:
            rev = await svc.revise_plan(
                db, chain_id=chain_id,
                actor_user_id=user.id, actor_org_id=user.org_id,
                kind=suggestion.kind, new_tail=suggestion.new_tail,
                reason=f"[reflect/{body.trigger}] {suggestion.reason}",
                registry=reg,
            )
            payload["applied"] = svc.revision_to_dict(rev)
        except svc.TaskChainError as e:
            payload["apply_error"] = str(e)
    return payload


@router.post("/{chain_id}/cancel", response_model=dict[str, Any])
async def api_cancel(
    chain_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        chain = await svc.cancel_chain(
            db, chain_id=chain_id,
            actor_user_id=user.id, actor_org_id=user.org_id,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))
    return svc.chain_to_dict(chain)


# ============ Approval endpoints (v2.1 E2.5) ============


class ApprovalDecisionIn(BaseModel):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    reason: str = Field(..., min_length=1, max_length=1024)
    modifications: dict[str, Any] | None = None


@router.get("/approvals/pending", response_model=dict[str, Any])
async def api_list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List task-chain approvals awaiting decision in the caller's org."""
    rows = await svc.list_pending_approvals_for_org(
        db, org_id=user.org_id, limit=limit,
    )
    items = []
    for approval, chain in rows:
        items.append({
            "approval": svc.approval_to_dict(approval),
            "chain": {
                "id": str(chain.id),
                "goal": chain.goal,
                "status": chain.status,
                "current_index": chain.current_index,
            },
        })
    return {"items": items}


@router.get("/{chain_id}/approvals", response_model=dict[str, Any])
async def api_list_chain_approvals(
    chain_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        await svc.get_chain(db, chain_id=chain_id, viewer_org_id=user.org_id)
    except svc.TaskChainError as e:
        raise HTTPException(404, str(e))
    rows = await svc.list_approvals(db, chain_id=chain_id)
    return {"items": [svc.approval_to_dict(r) for r in rows]}


@router.post("/approvals/{approval_id}/decide", response_model=dict[str, Any])
async def api_decide_approval(
    approval_id: UUID,
    body: ApprovalDecisionIn,
    resume: bool = Query(True, description="If approved, immediately re-run the step."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    # Only privileged roles may decide
    if getattr(user, "role", None) not in ("admin", "org_admin", "approver", "owner"):
        raise HTTPException(403, "user role cannot decide approvals")
    try:
        approval = await svc.decide_approval(
            db, approval_id=approval_id,
            approver_id=user.id, approver_org_id=user.org_id,
            decision=body.decision, decision_reason=body.reason,
            modifications=body.modifications,
        )
    except svc.TaskChainError as e:
        raise HTTPException(400, str(e))

    payload: dict[str, Any] = {"approval": svc.approval_to_dict(approval)}
    if body.decision == "approved" and resume:
        reg = build_default_registry()
        try:
            r = await svc.resume_after_approval(
                db, chain_id=approval.chain_id,
                executor_user_id=user.id, executor_org_id=user.org_id,
                registry=reg, tool_ctx_factory=_ctx_factory(db, user),
            )
            if r is not None:
                payload["resumed_step"] = svc.step_to_dict(r.step)
                payload["chain"] = svc.chain_to_dict(r.chain)
        except svc.TaskChainError as e:
            payload["resume_error"] = str(e)
    return payload

