"""3DGS Reality Studio API — v2.1 T1.

Endpoints
---------

* ``POST /scenes``                — create scene (draft)
* ``GET  /scenes``                — list scenes (org-scoped)
* ``GET  /scenes/{id}``           — fetch scene + assets
* ``PATCH /scenes/{id}``          — update name / description / archive
* ``POST /scenes/{id}/ingest``    — draft → ingesting → ingested
* ``POST /scenes/{id}/colmap``    — ingested → colmap → colmap_done
* ``POST /scenes/{id}/train``     — colmap_done → training → ready
* ``POST /scenes/{id}/reset``     — failed → draft
* ``POST /scenes/{id}/archive``   — any non-terminal → archived
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.scene import SCENE_STATUSES, Scene, SceneAsset
from app.models.user import User
from app.services import scene_pipeline as sp


router = APIRouter(prefix="/scenes", tags=["scenes"])


# ---------- Schemas --------------------------------------------------------


class SceneAssetOut(BaseModel):
    id: UUID
    kind: str
    filename: str
    size_bytes: Optional[int]
    sha256_hex: Optional[str]

    class Config:
        from_attributes = True


class SceneOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    status: str
    error_msg: Optional[str]
    coord_system: Optional[str]
    n_source_images: int
    n_points: Optional[int]
    n_gaussians: Optional[int]
    psnr_train: Optional[float]
    mission_id: Optional[UUID]
    assets: list[SceneAssetOut] = []

    class Config:
        from_attributes = True


class SceneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    coord_system: Optional[str] = Field(None, max_length=40)
    mission_id: Optional[UUID] = None


class SceneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    coord_system: Optional[str] = Field(None, max_length=40)


class ScenesList(BaseModel):
    total: int
    scenes: list[SceneOut]


# ---------- Helpers --------------------------------------------------------


def _to_out(scene: Scene) -> SceneOut:
    return SceneOut(
        id=scene.id,
        name=scene.name,
        description=scene.description,
        status=scene.status,
        error_msg=scene.error_msg,
        coord_system=scene.coord_system,
        n_source_images=scene.n_source_images,
        n_points=scene.n_points,
        n_gaussians=scene.n_gaussians,
        psnr_train=scene.psnr_train,
        mission_id=scene.mission_id,
        assets=[
            SceneAssetOut.model_validate(a)
            for a in (scene.assets or [])
        ],
    )


async def _load_with_assets(db: AsyncSession, scene_id: UUID) -> Scene:
    from sqlalchemy.orm import selectinload

    stmt = select(Scene).options(selectinload(Scene.assets)).where(Scene.id == scene_id)
    scene = (await db.execute(stmt)).scalar_one_or_none()
    if scene is None:
        raise HTTPException(404, f"scene {scene_id} not found")
    return scene


# ---------- CRUD -----------------------------------------------------------


@router.post("", response_model=SceneOut, status_code=201)
async def create_scene(
    body: SceneCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = Scene(
        name=body.name,
        description=body.description,
        coord_system=body.coord_system,
        mission_id=body.mission_id,
        org_id=user.org_id,
        owner_user_id=user.id,
        status="draft",
    )
    db.add(scene)
    await db.commit()
    await db.refresh(scene)
    return _to_out(scene)


@router.get("", response_model=ScenesList)
async def list_scenes(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScenesList:
    stmt = select(Scene).order_by(Scene.created_at.desc())
    # Org-scope: user can only see scenes in their org (or their own if orgless)
    if user.org_id:
        stmt = stmt.where(Scene.org_id == user.org_id)
    else:
        stmt = stmt.where(Scene.owner_user_id == user.id)
    if status:
        if status not in SCENE_STATUSES:
            raise HTTPException(400, f"unknown status {status!r}")
        stmt = stmt.where(Scene.status == status)
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return ScenesList(total=len(rows), scenes=[_to_out(r) for r in rows])


@router.get("/{scene_id}", response_model=SceneOut)
async def get_scene(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_read(scene, user)
    return _to_out(scene)


@router.patch("/{scene_id}", response_model=SceneOut)
async def update_scene(
    scene_id: UUID,
    body: SceneUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    if body.name is not None:
        scene.name = body.name
    if body.description is not None:
        scene.description = body.description
    if body.coord_system is not None:
        scene.coord_system = body.coord_system
    await db.commit()
    await db.refresh(scene)
    return _to_out(scene)


# ---------- Pipeline transitions -------------------------------------------


@router.post("/{scene_id}/ingest", response_model=SceneOut)
async def start_ingest(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    try:
        await sp.transition(db, scene, "ingesting")
        # In v2.1 T1 the upload endpoint handles assets; for now we complete
        # ingest immediately based on n_source_images >= 1
        if scene.n_source_images < 1:
            await sp.transition(db, scene, "failed", error_msg="no source images uploaded")
        else:
            await sp.transition(db, scene, "ingested")
    except sp.InvalidTransition as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return _to_out(scene)


@router.post("/{scene_id}/colmap", response_model=SceneOut)
async def start_colmap(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    try:
        await sp.start_colmap(db, scene)
    except sp.InvalidTransition as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return _to_out(scene)


@router.post("/{scene_id}/train", response_model=SceneOut)
async def start_train(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    try:
        await sp.start_training(db, scene)
    except sp.InvalidTransition as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return _to_out(scene)


@router.post("/{scene_id}/reset", response_model=SceneOut)
async def reset_scene(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    try:
        await sp.transition(db, scene, "draft")
    except sp.InvalidTransition as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return _to_out(scene)


@router.post("/{scene_id}/archive", response_model=SceneOut)
async def archive_scene(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SceneOut:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    try:
        await sp.transition(db, scene, "archived")
    except sp.InvalidTransition as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return _to_out(scene)


# ---------------------------------------------------------------------------
# T4.11 — Scene ingestion progress SSE
#
# EventSource can't send custom headers, so we accept the token via the
# ?token= query string. Auth is enforced identically to get_current_user.
# ---------------------------------------------------------------------------
@router.get("/{scene_id}/progress.sse")
async def scene_progress_sse(
    scene_id: UUID,
    request: Request,
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events feed of a scene's status + metrics.

    Emits one JSON payload per second until the scene reaches a
    terminal status (``ready`` / ``failed`` / ``archived``) or the
    client disconnects. Terminal status also fires a synthetic
    ``event: done`` frame so the browser EventSource can decide to
    ``close()`` without polling forever.

    Payload shape (data:):
      {
        "scene_id": "...",
        "status": "draft|ingesting|colmap|training|ready|failed|archived",
        "n_source_images": int,
        "n_points": int|null,
        "n_gaussians": int|null,
        "psnr_train": float|null,
        "error_msg": string|null,
        "updated_at": ISO-8601,
        "ts": ISO-8601 (server 'now'),
      }
    """
    import asyncio
    import json
    from datetime import datetime, timezone

    from fastapi.responses import StreamingResponse
    from jose import JWTError

    from app.services.auth import decode_token
    from app.models.user import User as _User

    # Resolve the user: prefer Authorization header, fall back to ?token=
    auth_header = request.headers.get("authorization")
    raw_token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:]
    elif token:
        raw_token = token
    if not raw_token:
        raise HTTPException(
            status_code=401, detail="Missing bearer token",
        )
    try:
        payload = decode_token(raw_token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Malformed token")
    user = (
        await db.execute(select(_User).where(_User.id == UUID(sub)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    scene = await _load_with_assets(db, scene_id)
    _authz_read(scene, user)

    TERMINAL = {"ready", "failed", "archived"}

    def _snapshot(scene_row: Scene) -> dict:
        return {
            "scene_id": str(scene_row.id),
            "status": scene_row.status,
            "n_source_images": scene_row.n_source_images or 0,
            "n_points": scene_row.n_points,
            "n_gaussians": scene_row.n_gaussians,
            "psnr_train": scene_row.psnr_train,
            "error_msg": scene_row.error_msg,
            "updated_at": (
                scene_row.updated_at.isoformat()
                if scene_row.updated_at else None
            ),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # v2.1: pub/sub via AsyncBroadcaster instead of per-request DB poll.
    # scene_job.py publishes state transitions to topic scene:<id>.
    from app.services.async_broadcaster import get_broadcaster
    broadcaster = get_broadcaster()
    topic = f"scene:{scene_id}"

    # Fallback safety: max 30 min per SSE connection (proxy-friendly).
    MAX_DURATION_SEC = 60 * 30

    async def _gen():
        import time as _time
        deadline = _time.monotonic() + MAX_DURATION_SEC

        # Compute current snapshot as SSE initial frame.
        initial = _snapshot(scene)

        try:
            async for event in broadcaster.subscribe(
                topic,
                initial=initial,
                heartbeat_interval=15.0,
            ):
                if _time.monotonic() >= deadline:
                    yield "event: timeout\ndata: {}\n\n"
                    return

                if event is None:
                    # Heartbeat comment doubles as keep-alive for proxies.
                    yield ": keepalive\n\n"
                    continue

                # Special event kinds
                kind = event.get("_event")
                if kind == "gone":
                    yield "event: gone\ndata: {}\n\n"
                    return

                yield f"data: {json.dumps(event)}\n\n"

                if event.get("status") in TERMINAL:
                    yield "event: done\ndata: {}\n\n"
                    return
        except asyncio.CancelledError:
            # Client disconnected — subscribe generator's finally cleans up.
            raise

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- Authz helpers --------------------------------------------------


def _authz_read(scene: Scene, user: User) -> None:
    if user.role == "admin":
        return
    if user.org_id and scene.org_id and user.org_id == scene.org_id:
        return
    if scene.owner_user_id == user.id:
        return
    raise HTTPException(403, "scene not visible")


def _authz_write(scene: Scene, user: User) -> None:
    if user.role == "admin":
        return
    if scene.owner_user_id == user.id:
        return
    if user.org_id and scene.org_id and user.org_id == scene.org_id and user.role in (
        "system_officer",
    ):
        return
    raise HTTPException(403, "scene not writable")
