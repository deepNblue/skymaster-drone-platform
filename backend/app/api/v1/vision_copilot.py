"""Vision AI + Copilot Agent REST endpoints — v2.0 R20 Track B.

Two logically-separate routers merged into a single module for cohesion:

  * ``/api/v1/vision/*``   — Vision AI Edge Runtime
  * ``/api/v1/copilot/*``  — Copilot Agent conversation
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.vision_copilot import CopilotSessionV2, CopilotTurnV2, VisionDetection
from app.services.copilot_intent import parse_intent, plan_tool_call, render_reply, run_turn
from app.services.copilot_bus import execute_tool_call, is_executable
from app.services.vision_runtime import (
    DetectionFrame, decode_base64_image, get_active_runtime, list_runtimes,
)
from app.services.vision_stream import build_frame_payload, publish_vision_frame

vision_router = APIRouter(prefix="/vision", tags=["vision-ai"])
copilot_router = APIRouter(prefix="/copilot", tags=["copilot-agent"])


# ============================================================
# Vision AI
# ============================================================


class InferBody(BaseModel):
    image_b64: str | None = Field(default=None, description="Optional base64 image")
    hint: str | None = None
    frame_idx: int | None = None
    drone_id: UUID | None = None
    mission_id: UUID | None = None
    stream_key: str | None = None
    lat: float | None = None
    lng: float | None = None
    alt_m: float | None = None
    frame_ts: datetime | None = None
    persist: bool = True


class DetectionOut(BaseModel):
    id: UUID
    label: str
    confidence: float
    bbox: list[float] | None
    lat: float | None
    lng: float | None
    alt_m: float | None
    drone_id: UUID | None
    mission_id: UUID | None
    stream_key: str | None
    model_tag: str | None
    runtime: str | None
    status: str
    frame_idx: int | None
    frame_ts: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class InferResponse(BaseModel):
    runtime: str
    model_tag: str
    latency_ms: float
    detections: list[dict[str, Any]]
    persisted: list[UUID] = []


@vision_router.get("/runtimes")
async def vision_runtimes(_: User = Depends(get_current_user)) -> dict:
    return {
        "available": list_runtimes(),
        "active": (settings.vision_runtime or "mock").lower(),
        "persist_threshold": settings.vision_persist_threshold,
    }


@vision_router.post("/infer", response_model=InferResponse)
async def vision_infer(
    body: InferBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InferResponse:
    image = decode_base64_image(body.image_b64) if body.image_b64 else None
    rt = get_active_runtime()
    result: DetectionFrame = await rt.infer(
        image_bytes=image, frame_idx=body.frame_idx, hint=body.hint,
    )

    persisted: list[UUID] = []
    if body.persist:
        thr = settings.vision_persist_threshold
        rows: list[VisionDetection] = []
        for d in result.detections:
            if d.confidence < thr:
                continue
            row = VisionDetection(
                tenant_id=getattr(user, "org_id", None),
                drone_id=body.drone_id,
                mission_id=body.mission_id,
                stream_key=body.stream_key,
                label=d.label,
                confidence=d.confidence,
                bbox=d.bbox,
                lat=body.lat, lng=body.lng, alt_m=body.alt_m,
                frame_ts=body.frame_ts, frame_idx=body.frame_idx,
                model_tag=result.model_tag,
                runtime=result.runtime,
                status="new",
                meta={"attrs": d.attrs, "track_id": d.track_id},
            )
            db.add(row)
            rows.append(row)
        if rows:
            await db.commit()
            for r in rows:
                await db.refresh(r)
                persisted.append(r.id)

    # Fan-out to WebSocket subscribers via Redis pub/sub. Publishing runs
    # *after* the DB commit so any `persisted_ids` are already stable —
    # the browser overlay can then look up detail if needed. Any Redis
    # failure is non-fatal; the API still returns 200.
    try:
        payload = build_frame_payload(
            result=result,
            drone_id=str(body.drone_id) if body.drone_id else None,
            mission_id=str(body.mission_id) if body.mission_id else None,
            stream_key=body.stream_key,
            lat=body.lat, lng=body.lng, alt_m=body.alt_m,
            persisted_ids=[str(x) for x in persisted],
        )
        await publish_vision_frame(
            getattr(request.app.state, "redis", None),
            payload,
            drone_id=str(body.drone_id) if body.drone_id else None,
        )
    except Exception:  # pragma: no cover
        pass

    return InferResponse(
        runtime=result.runtime,
        model_tag=result.model_tag,
        latency_ms=result.latency_ms,
        detections=[
            {
                "label": d.label,
                "confidence": d.confidence,
                "bbox": d.bbox,
                "track_id": d.track_id,
                "attrs": d.attrs,
            } for d in result.detections
        ],
        persisted=persisted,
    )


@vision_router.get("/detections", response_model=list[DetectionOut])
async def list_detections(
    label: Optional[str] = None,
    drone_id: Optional[UUID] = None,
    mission_id: Optional[UUID] = None,
    status: Optional[str] = None,
    since_minutes: int = 60,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VisionDetection]:
    q = select(VisionDetection)
    if label:
        q = q.where(VisionDetection.label == label)
    if drone_id:
        q = q.where(VisionDetection.drone_id == drone_id)
    if mission_id:
        q = q.where(VisionDetection.mission_id == mission_id)
    if status:
        q = q.where(VisionDetection.status == status)
    if since_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        q = q.where(VisionDetection.created_at >= cutoff)
    q = q.order_by(desc(VisionDetection.created_at)).limit(min(limit, 500))
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@vision_router.post("/detections/{det_id}/ack", response_model=DetectionOut)
async def ack_detection(
    det_id: UUID,
    status: str = "acknowledged",
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisionDetection:
    if status not in {"acknowledged", "dismissed", "escalated"}:
        raise HTTPException(400, "invalid status")
    row = await db.get(VisionDetection, det_id)
    if row is None:
        raise HTTPException(404, "detection not found")
    row.status = status
    await db.commit()
    await db.refresh(row)
    return row


# ============================================================
# Copilot Agent
# ============================================================


class SessionCreateBody(BaseModel):
    title: str = "新会话"
    persona: str = Field(default="operator", pattern="^(operator|analyst|instructor)$")
    system_prompt: str | None = None


class SessionOut(BaseModel):
    id: UUID
    title: str
    persona: str
    created_at: datetime

    class Config:
        from_attributes = True


class TurnBody(BaseModel):
    text: str
    drone_id: UUID | None = None
    execute: bool = False  # if True, backend attempts to invoke the planned tool


class TurnOut(BaseModel):
    id: UUID
    turn_idx: int
    user_text: str
    intent: str | None
    args: dict | None
    reply_text: str | None
    tool_call: dict | None
    tool_result: dict | None
    status: str
    latency_ms: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class DryRunResponse(BaseModel):
    intent: str
    args: dict
    confidence: float
    reply: str
    tool_call: dict | None


@copilot_router.post("/dry-run", response_model=DryRunResponse)
async def copilot_dry_run(
    body: TurnBody,
    _: User = Depends(get_current_user),
) -> DryRunResponse:
    """Preview intent parsing without touching the database.

    Useful for the UI hint bubble as the operator types.
    """
    result = run_turn(body.text, drone_id=str(body.drone_id) if body.drone_id else None)
    return DryRunResponse(
        intent=result["intent"],
        args=result["args"] or {},
        confidence=result["confidence"],
        reply=result["reply_text"],
        tool_call=result["tool_call"],
    )


@copilot_router.post("/sessions", response_model=SessionOut)
async def create_session(
    body: SessionCreateBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CopilotSessionV2:
    sess = CopilotSessionV2(
        tenant_id=getattr(user, "org_id", None),
        user_id=user.id,
        title=body.title,
        persona=body.persona,
        system_prompt=body.system_prompt,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


@copilot_router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CopilotSessionV2]:
    q = select(CopilotSessionV2).where(CopilotSessionV2.user_id == user.id)
    q = q.order_by(desc(CopilotSessionV2.created_at)).limit(100)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@copilot_router.get("/sessions/{sid}/turns", response_model=list[TurnOut])
async def list_turns(
    sid: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CopilotTurnV2]:
    sess = await db.get(CopilotSessionV2, sid)
    if sess is None or (sess.user_id and sess.user_id != user.id):
        raise HTTPException(404, "session not found")
    q = select(CopilotTurnV2).where(CopilotTurnV2.session_id == sid).order_by(CopilotTurnV2.turn_idx)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@copilot_router.post("/sessions/{sid}/turns", response_model=TurnOut)
async def create_turn(
    sid: UUID,
    body: TurnBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CopilotTurnV2:
    sess = await db.get(CopilotSessionV2, sid)
    if sess is None or (sess.user_id and sess.user_id != user.id):
        raise HTTPException(404, "session not found")

    # Enumerate current turn index.
    prev_count = (await db.execute(
        select(CopilotTurnV2.turn_idx)
        .where(CopilotTurnV2.session_id == sid)
        .order_by(desc(CopilotTurnV2.turn_idx))
        .limit(1)
    )).scalar_one_or_none() or 0
    next_idx = prev_count + 1

    # R21 G — Multi-turn context: replay the last N turns of THIS session
    # into a ContextState, then apply it to the new parse to backfill
    # missing slots ("再飞高 20m", "回到刚才的位置", "返航").
    from app.services.copilot_context import load_context, apply_context
    from app.services.copilot_intent import parse_intent, plan_tool_call, render_reply
    import time as _t
    _t0 = _t.monotonic()
    ctx = await load_context(db, sid)
    parsed_raw = parse_intent(body.text)
    parsed = apply_context(parsed_raw, ctx)
    tool_call = plan_tool_call(
        parsed,
        drone_id=str(body.drone_id) if body.drone_id else (ctx.drone_id or None),
    )
    reply_text = render_reply(parsed)
    planned = {
        "intent": parsed.intent,
        "args": parsed.args,
        "confidence": parsed.confidence,
        "reply_text": reply_text,
        "tool_call": tool_call,
        "tool_result": None,
        "status": "clarify" if parsed.intent == "unknown" else "ok",
        "latency_ms": round((_t.monotonic() - _t0) * 1000, 3),
    }

    # execute=True → dispatch through the copilot command bus. Bus is
    # permission-gated and shape-safe: it will only touch drone commands
    # that already have wired routes, and it will never elevate the
    # actor's role. Any failure returns a structured tool_result so the
    # turn is stored end-to-end even when the sim/drone is unreachable.
    tool_result: dict | None = planned["tool_result"]
    turn_status: str = planned["status"]
    if body.execute and planned["tool_call"]:
        tool_result = execute_tool_call(
            planned["tool_call"],
            actor=user,
            drone_id=str(body.drone_id) if body.drone_id else None,
        )
        # Preserve clarify status; only overwrite an ok-plan with a
        # bus-reported failure.
        if turn_status == "ok" and tool_result.get("status") in {"error", "denied"}:
            turn_status = tool_result["status"]

    row = CopilotTurnV2(
        session_id=sid,
        turn_idx=next_idx,
        user_text=body.text,
        intent=planned["intent"],
        args=planned["args"],
        reply_text=planned["reply_text"],
        tool_call=planned["tool_call"],
        tool_result=tool_result,
        status=turn_status,
        latency_ms=int(planned["latency_ms"]),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
