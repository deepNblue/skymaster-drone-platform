"""Copilot v0.1 HTTP API (SDD v2.0-C §6).

Endpoints:

* ``POST   /copilot/sessions``               — create a session
* ``POST   /copilot/sessions/{sid}/messages`` — SSE stream of a Copilot turn
* ``GET    /copilot/sessions/{sid}/traces``   — list traces for a session
* ``GET    /copilot/traces/{tid}``            — get a single trace (with steps)
* ``POST   /copilot/traces/{tid}/approve``    — decide on a pending approval
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal, get_db
from app.deps import get_current_user
from app.models.copilot_approval import CopilotApproval
from app.models.copilot_session import CopilotSession
from app.models.copilot_trace import CopilotTrace
from app.models.copilot_trace_step import CopilotTraceStep
from app.models.user import User
from app.schemas.copilot import (
    ApprovalDecision,
    MessageRequest,
    TraceOut,
    TraceStepOut,
)
from app.services.copilot_agent import CopilotAgent
from app.services.copilot_agent_v2 import AgentConfig, CopilotAgentV2
from app.services.llm_client import LLMClient
from app.services.tool_registry import ToolContext, build_default_registry


router = APIRouter(prefix="/copilot", tags=["copilot"])


def _build_agent() -> CopilotAgent:
    """Wire an agent instance from current settings."""
    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        protocol=settings.llm_protocol,
    )
    registry = build_default_registry()
    return CopilotAgent(llm, registry)


def _build_agent_v2() -> CopilotAgentV2:
    """Wire a v2 (Function Calling loop) agent instance."""
    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        protocol=settings.llm_protocol,
    )
    registry = build_default_registry()
    return CopilotAgentV2(llm, registry, AgentConfig())


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    row = CopilotSession(org_id=user.org_id, user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"session_id": str(row.id)}


# ---------------------------------------------------------------------------
# Messages (SSE)
# ---------------------------------------------------------------------------
@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: UUID,
    payload: MessageRequest,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Run one Copilot turn and stream events as SSE.

    A fresh DB session is used inside the generator because the request-
    scoped session ends when this coroutine returns (immediately, so the
    StreamingResponse can start).
    """
    # Verify tenancy up front using a short-lived session.
    async with AsyncSessionLocal() as verify_db:
        row = (
            await verify_db.execute(
                select(CopilotSession).where(CopilotSession.id == session_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="session not found",
            )
        if row.org_id is not None and row.org_id != user.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="session belongs to another org",
            )

    agent = _build_agent()

    async def event_gen() -> AsyncGenerator[bytes, None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(evt: dict[str, Any]) -> None:
            await queue.put(evt)

        async def worker() -> None:
            async with AsyncSessionLocal() as db_run:
                ctx = ToolContext(
                    db=db_run, org_id=user.org_id, user_id=user.id
                )
                try:
                    await agent.run(
                        payload.prompt,
                        ctx,
                        emit,
                        session_id=session_id,
                        db=db_run,
                    )
                finally:
                    await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse_frame(item)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Messages v2 — Function Calling loop (T4.0)
# ---------------------------------------------------------------------------
@router.post("/v2/sessions/{session_id}/messages")
async def post_message_v2(
    session_id: UUID,
    payload: MessageRequest,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Full Function-Calling loop with tool_use / tool_result cycling.

    v2 differs from v1 in two ways:
      1. Tools are dispatched via the LLM's structured tool_use output
         (Anthropic Function Calling or OpenAI tool_calls), not by an
         intent-classifier heuristic.
      2. Sensitive tools (create/dispatch/abort mission) do NOT execute
         immediately — the loop enqueues a CopilotApproval row and emits
         an ``approval_required`` SSE event; the approve endpoint resumes.
    """
    async with AsyncSessionLocal() as verify_db:
        row = (
            await verify_db.execute(
                select(CopilotSession).where(CopilotSession.id == session_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "session not found")
        if row.org_id is not None and row.org_id != user.org_id:
            raise HTTPException(403, "session belongs to another org")

    agent = _build_agent_v2()

    async def event_gen() -> AsyncGenerator[bytes, None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(evt: dict[str, Any]) -> None:
            await queue.put(evt)

        async def worker() -> None:
            async with AsyncSessionLocal() as db_run:
                # Create a trace row for this turn
                trace = CopilotTrace(
                    id=uuid4(),
                    session_id=session_id, org_id=user.org_id,
                    user_id=user.id,
                    prompt=payload.prompt, status="running",
                )
                db_run.add(trace)
                await db_run.commit()
                await db_run.refresh(trace)

                ctx = ToolContext(db=db_run, org_id=user.org_id, user_id=user.id)
                try:
                    result = await agent.run(
                        payload.prompt, history=None, ctx=ctx,
                        emit_cb=emit,
                        session_id=session_id, trace_id=trace.id, db=db_run,
                    )
                    trace.status = (
                        "awaiting_approval"
                        if result["stopped_reason"] == "approval_required"
                        else "completed"
                        if result["stopped_reason"] == "end"
                        else "error"
                    )
                    trace.output = {
                        "text": result.get("text") or "",
                        "tool_calls": result.get("tool_calls") or [],
                        "pending_approvals": result.get("pending_approvals") or [],
                        "stopped_reason": result.get("stopped_reason"),
                    }
                    trace.ended_at = datetime.now(timezone.utc)
                    await db_run.commit()
                finally:
                    await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse_frame(item)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_gen(), media_type="text/event-stream")
    """Format a dict as an ``event: X\\ndata: {..}\\n\\n`` SSE frame."""
    evt_type = str(evt.get("type") or "message")
    data = evt.get("data")
    body = json.dumps(data, ensure_ascii=False, default=str) if data is not None else "{}"
    return f"event: {evt_type}\ndata: {body}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Trace listing
# ---------------------------------------------------------------------------
@router.get("/sessions/{session_id}/traces")
async def list_traces(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TraceOut]:
    session_row = (
        await db.execute(
            select(CopilotSession).where(CopilotSession.id == session_id)
        )
    ).scalar_one_or_none()
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    if session_row.org_id is not None and session_row.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="session belongs to another org",
        )

    rows = (
        await db.execute(
            select(CopilotTrace)
            .where(CopilotTrace.session_id == session_id)
            .order_by(CopilotTrace.started_at.desc())
        )
    ).scalars().all()
    return [TraceOut.model_validate(r) for r in rows]


@router.get("/traces/{trace_id}")
async def get_trace(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TraceOut:
    trace = (
        await db.execute(
            select(CopilotTrace).where(CopilotTrace.id == trace_id)
        )
    ).scalar_one_or_none()
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trace not found"
        )
    if trace.org_id is not None and trace.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="trace belongs to another org",
        )
    steps = (
        await db.execute(
            select(CopilotTraceStep)
            .where(CopilotTraceStep.trace_id == trace_id)
            .order_by(CopilotTraceStep.idx.asc())
        )
    ).scalars().all()
    out = TraceOut.model_validate(trace)
    out.steps = [TraceStepOut.model_validate(s) for s in steps]
    return out


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
@router.post("/approvals/bulk")
async def bulk_approve_traces(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Batch approve/reject multiple pending traces.

    Body: {"trace_ids": ["...", ...], "decision": "approved"|"rejected",
           "comment": "optional"}

    Behavior:
      - Non-existent or non-pending trace_ids are skipped (reported in result)
      - Non-admin actors can only operate on traces within their org
      - Emits one audit line per trace via the standard middleware
    """
    trace_ids = body.get("trace_ids") or []
    decision = body.get("decision")
    comment = body.get("comment")
    if not trace_ids or decision not in ("approved", "rejected", "modified"):
        raise HTTPException(400, "trace_ids + decision required")

    from uuid import UUID
    parsed: list[UUID] = []
    for tid in trace_ids:
        try:
            parsed.append(UUID(tid))
        except (ValueError, TypeError):
            continue

    if not parsed:
        raise HTTPException(400, "no valid trace_ids")

    stmt = select(CopilotTrace).where(CopilotTrace.id.in_(parsed))
    if user.role != "admin" and user.org_id is not None:
        stmt = stmt.where(CopilotTrace.org_id == user.org_id)
    rows = (await db.execute(stmt)).scalars().all()

    approved: list[str] = []
    skipped: list[dict] = []
    for r in rows:
        if r.status != "pending":
            skipped.append({"trace_id": str(r.id), "reason": f"status={r.status}"})
            continue
        r.status = decision
        approved.append(str(r.id))

    await db.commit()
    return {
        "requested": len(trace_ids),
        "processed": len(approved),
        "approved_ids": approved,
        "skipped": skipped,
        "decision": decision,
        "comment": comment,
    }


@router.get("/approvals/pending")
async def list_pending_approvals(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return traces awaiting operator approval.

    Filters by ``org_id`` for non-admin users; admins see all pending
    across every org. Returns a lightweight summary (no steps) suitable
    for the approvals inbox UI.
    """
    stmt = (
        select(CopilotTrace)
        .where(CopilotTrace.status == "pending")
        .order_by(CopilotTrace.started_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    if user.role != "admin" and user.org_id is not None:
        stmt = stmt.where(CopilotTrace.org_id == user.org_id)
    rows = (await db.execute(stmt)).scalars().all()
    # Bulk fetch org names for display.
    org_ids = {r.org_id for r in rows if r.org_id}
    org_map: dict = {}
    if org_ids:
        from app.models.organization import Organization
        org_rows = (
            await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
        ).scalars().all()
        org_map = {o.id: o.name for o in org_rows}
    return [
        {
            "trace_id": str(r.id),
            "session_id": str(r.session_id) if r.session_id else None,
            "org_id": str(r.org_id) if r.org_id else None,
            "org_name": org_map.get(r.org_id) if r.org_id else None,
            "intent": r.intent,
            "prompt": (r.prompt or "")[:200],
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "status": r.status,
        }
        for r in rows
    ]


@router.post("/traces/{trace_id}/approve")
async def approve_trace(
    trace_id: UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    trace = (
        await db.execute(
            select(CopilotTrace).where(CopilotTrace.id == trace_id)
        )
    ).scalar_one_or_none()
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trace not found"
        )
    if trace.org_id is not None and trace.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="trace belongs to another org",
        )

    approval = (
        await db.execute(
            select(CopilotApproval).where(CopilotApproval.trace_id == trace_id)
        )
    ).scalar_one_or_none()
    if approval is None:
        approval = CopilotApproval(trace_id=trace_id)
        db.add(approval)

    approval.decision = decision.decision
    approval.modifications = decision.modifications
    approval.comment = decision.comment
    approval.approver_id = user.id
    approval.approved_at = datetime.now(timezone.utc)

    if decision.decision == "approved":
        trace.status = "approved"
    elif decision.decision == "rejected":
        trace.status = "rejected"
    else:  # modified
        trace.status = "modified"

    await db.commit()

    return {
        "trace_id": str(trace_id),
        "status": trace.status,
        "decision": decision.decision,
    }


__all__ = ["router"]
