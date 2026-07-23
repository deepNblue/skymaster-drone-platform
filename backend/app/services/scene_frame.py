"""D3.1 · Scene frame service — 4DGS timeline management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene import Scene
from app.models.scene_frame import SceneFrame, VALID_LIGHTING


class FrameError(Exception):
    """Domain error, mapped to HTTP 400/404 at REST layer."""


async def _load_scene(
    db: AsyncSession, *, scene_id: uuid.UUID, org_id: uuid.UUID,
) -> Scene:
    """Verify scene exists + belongs to caller's org, return it."""
    q = select(Scene).where(
        Scene.id == scene_id, Scene.org_id == org_id,
    )
    scene = (await db.execute(q)).scalar_one_or_none()
    if scene is None:
        raise FrameError("scene not found")
    return scene


async def create_frame(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    frame_index: int,
    captured_at: datetime | None = None,
    is_keyframe: bool = False,
    psnr_frame: float | None = None,
    lighting: str | None = None,
    notes: str | None = None,
    meta: dict[str, Any] | None = None,
) -> SceneFrame:
    scene = await _load_scene(db, scene_id=scene_id, org_id=org_id)
    if scene.scene_kind != "4dgs":
        raise FrameError("scene is not 4dgs, cannot attach frames")
    if frame_index < 0:
        raise FrameError("frame_index must be >= 0")
    if lighting is not None and lighting not in VALID_LIGHTING:
        raise FrameError(f"invalid lighting: {lighting}")

    row = SceneFrame(
        scene_id=scene_id,
        frame_index=frame_index,
        captured_at=captured_at,
        is_keyframe=is_keyframe,
        psnr_frame=psnr_frame,
        lighting=lighting,
        notes=notes,
        meta=meta or {},
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise FrameError(f"failed to create frame: {exc}")
    await db.refresh(row)
    return row


async def bulk_create_frames(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    entries: list[dict[str, Any]],
) -> list[SceneFrame]:
    """Insert many frames atomically.

    Each entry is a dict with the same keys as ``create_frame``.
    Idempotent guarantees are the caller's problem (unique constraint
    on (scene_id, frame_index) will still fire).
    """
    scene = await _load_scene(db, scene_id=scene_id, org_id=org_id)
    if scene.scene_kind != "4dgs":
        raise FrameError("scene is not 4dgs, cannot attach frames")
    rows: list[SceneFrame] = []
    for e in entries:
        idx = e.get("frame_index")
        if idx is None or int(idx) < 0:
            raise FrameError("frame_index must be provided and >= 0")
        light = e.get("lighting")
        if light is not None and light not in VALID_LIGHTING:
            raise FrameError(f"invalid lighting: {light}")
        rows.append(SceneFrame(
            scene_id=scene_id,
            frame_index=int(idx),
            captured_at=e.get("captured_at"),
            is_keyframe=bool(e.get("is_keyframe", False)),
            psnr_frame=e.get("psnr_frame"),
            lighting=light,
            notes=e.get("notes"),
            meta=e.get("meta") or {},
        ))
    db.add_all(rows)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise FrameError(f"bulk insert failed: {exc}")
    for r in rows:
        await db.refresh(r)
    return rows


async def get_frame(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    frame_index: int,
) -> SceneFrame | None:
    # Enforce org visibility via scene lookup.
    await _load_scene(db, scene_id=scene_id, org_id=org_id)
    q = select(SceneFrame).where(
        SceneFrame.scene_id == scene_id,
        SceneFrame.frame_index == frame_index,
    )
    return (await db.execute(q)).scalar_one_or_none()


async def list_frames(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    only_keyframes: bool = False,
    lighting: str | None = None,
) -> list[SceneFrame]:
    await _load_scene(db, scene_id=scene_id, org_id=org_id)
    conds = [SceneFrame.scene_id == scene_id]
    if only_keyframes:
        conds.append(SceneFrame.is_keyframe.is_(True))
    if lighting is not None:
        if lighting not in VALID_LIGHTING:
            raise FrameError(f"invalid lighting: {lighting}")
        conds.append(SceneFrame.lighting == lighting)
    q = select(SceneFrame).where(and_(*conds)).order_by(
        SceneFrame.frame_index.asc(),
    )
    return list((await db.execute(q)).scalars().all())


async def update_frame(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    frame_index: int,
    is_keyframe: bool | None = None,
    psnr_frame: float | None = None,
    lighting: str | None = None,
    notes: str | None = None,
    captured_at: datetime | None = None,
    meta: dict[str, Any] | None = None,
) -> SceneFrame:
    row = await get_frame(
        db, scene_id=scene_id, org_id=org_id, frame_index=frame_index,
    )
    if row is None:
        raise FrameError("frame not found")
    if is_keyframe is not None:
        row.is_keyframe = is_keyframe
    if psnr_frame is not None:
        row.psnr_frame = psnr_frame
    if lighting is not None:
        if lighting not in VALID_LIGHTING:
            raise FrameError(f"invalid lighting: {lighting}")
        row.lighting = lighting
    if notes is not None:
        row.notes = notes
    if captured_at is not None:
        row.captured_at = captured_at
    if meta is not None:
        row.meta = meta
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_frame(
    db: AsyncSession, *, scene_id: uuid.UUID, org_id: uuid.UUID,
    frame_index: int,
) -> bool:
    row = await get_frame(
        db, scene_id=scene_id, org_id=org_id, frame_index=frame_index,
    )
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def timeline_summary(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Return a scrubbable timeline summary for viewer UI.

    Includes total, keyframe count, first/last captured_at, avg PSNR,
    keyframe indices (for scrubber snap points).
    """
    await _load_scene(db, scene_id=scene_id, org_id=org_id)
    q_total = select(func.count(SceneFrame.id)).where(
        SceneFrame.scene_id == scene_id,
    )
    total = (await db.execute(q_total)).scalar_one() or 0

    q_key = select(func.count(SceneFrame.id)).where(
        SceneFrame.scene_id == scene_id,
        SceneFrame.is_keyframe.is_(True),
    )
    n_key = (await db.execute(q_key)).scalar_one() or 0

    q_time = select(
        func.min(SceneFrame.captured_at),
        func.max(SceneFrame.captured_at),
    ).where(SceneFrame.scene_id == scene_id)
    t_min, t_max = (await db.execute(q_time)).one()

    q_psnr = select(func.avg(SceneFrame.psnr_frame)).where(
        SceneFrame.scene_id == scene_id,
    )
    psnr_avg = (await db.execute(q_psnr)).scalar_one()

    q_key_idx = select(SceneFrame.frame_index).where(
        SceneFrame.scene_id == scene_id,
        SceneFrame.is_keyframe.is_(True),
    ).order_by(SceneFrame.frame_index.asc())
    key_indices = [
        r[0] for r in (await db.execute(q_key_idx)).all()
    ]

    return {
        "scene_id": str(scene_id),
        "total_frames": int(total),
        "keyframe_count": int(n_key),
        "keyframe_indices": key_indices,
        "captured_at_start": t_min.isoformat() if t_min else None,
        "captured_at_end": t_max.isoformat() if t_max else None,
        "avg_psnr": float(psnr_avg) if psnr_avg is not None else None,
    }
