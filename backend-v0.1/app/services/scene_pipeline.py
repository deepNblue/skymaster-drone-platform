"""3DGS scene pipeline — v2.1 T1.

State machine + orchestrator for the reconstruction pipeline. The heavy
compute (COLMAP SfM, Gaussian splatting training) is intentionally
**stubbed** at this layer — an ``Executor`` protocol lets us plug in:

* ``NoOpExecutor``     — dev/test, transitions state instantly.
* ``ColmapExecutor``   — shells out to COLMAP binary (future).
* ``GsplatExecutor``   — shells out to Nerfstudio/gsplat trainer (future).
* ``QueueExecutor``    — pushes to a Celery/RQ queue for real workers.

Why stubbed?
------------

R23 收官后立刻推 3DGS 真训练是 v2.1 T1 的收尾环节；本轮先落地 API +
状态机 + 授权门槛 + 数据库表 + 前端骨架，把接口稳定下来。真训练器接
入放在 T1.5 — 那时候可以选 nerfstudio-gsplat vs Inria 原版做对比。

State machine (only these transitions are legal):

    draft ─────► ingesting ─► ingested ─► colmap ─► colmap_done ─► training ─► ready
      │             │             │          │             │              │
      │             ▼             │          ▼             ▼              ▼
      └──────► failed ◄────────────────────────────────────────────────── failed
                 │
                 └── after user reset ──► draft

Any state may transition to ``archived`` from the API side, but the
pipeline itself never transitions into archived.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene import SCENE_STATUSES, Scene

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State-machine
# ---------------------------------------------------------------------------

# Forward legal transitions. NB: this must remain a pure Python dict —
# tests key off it directly.
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"ingesting", "archived", "failed"},
    "ingesting": {"ingested", "failed", "draft"},  # allow revert
    "ingested": {"colmap", "failed", "archived"},
    "colmap": {"colmap_done", "failed"},
    "colmap_done": {"training", "failed", "archived"},
    "training": {"ready", "failed"},
    "ready": {"archived"},
    "failed": {"draft", "archived"},  # reset → draft, or archive it
    "archived": set(),  # terminal
}


class InvalidTransition(ValueError):
    pass


def can_transition(from_st: str, to_st: str) -> bool:
    if from_st not in SCENE_STATUSES or to_st not in SCENE_STATUSES:
        return False
    return to_st in _LEGAL_TRANSITIONS.get(from_st, set())


async def transition(
    db: AsyncSession, scene: Scene, to_status: str, *, error_msg: Optional[str] = None
) -> Scene:
    if not can_transition(scene.status, to_status):
        raise InvalidTransition(
            f"cannot go {scene.status!r} → {to_status!r}"
        )
    scene.status = to_status
    if to_status == "failed":
        scene.error_msg = error_msg or scene.error_msg or "unknown"
    else:
        # Clear stale error when moving off of failed.
        scene.error_msg = None
    await db.flush()

    # v2.1: publish state transition to SSE broadcaster so subscribers
    # (scenes.py stream_scene_progress) receive real-time updates without
    # having to poll the database. Safe no-op when no active subscribers.
    try:
        from datetime import datetime, timezone
        from app.services.async_broadcaster import get_broadcaster

        get_broadcaster()  # ensure singleton
        broadcaster = get_broadcaster()
        await broadcaster.publish(
            f"scene:{scene.id}",
            {
                "scene_id": str(scene.id),
                "status": scene.status,
                "n_source_images": scene.n_source_images or 0,
                "n_points": scene.n_points,
                "n_gaussians": scene.n_gaussians,
                "psnr_train": scene.psnr_train,
                "error_msg": scene.error_msg,
                "updated_at": (
                    scene.updated_at.isoformat()
                    if scene.updated_at else None
                ),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:  # pragma: no cover — publish must not break DB tx
        import logging
        logging.getLogger(__name__).warning(
            "scene state publish failed (non-fatal)", exc_info=True
        )

    return scene


# ---------------------------------------------------------------------------
# Executor protocol (stubbed in v2.1 T1 · real integration lives in T1.5)
# ---------------------------------------------------------------------------


@dataclass
class ExecResult:
    ok: bool
    error: Optional[str] = None
    # Populated on success — feeds Scene summary metrics.
    n_points: Optional[int] = None
    n_gaussians: Optional[int] = None
    psnr_train: Optional[float] = None


class Executor(ABC):
    """Pluggable compute backend."""

    @abstractmethod
    async def run_colmap(self, scene_id: UUID) -> ExecResult: ...

    @abstractmethod
    async def run_training(self, scene_id: UUID) -> ExecResult: ...


class NoOpExecutor(Executor):
    """Instant-success executor for dev/tests. Returns fake but plausible metrics."""

    async def run_colmap(self, scene_id: UUID) -> ExecResult:  # noqa: ARG002
        await asyncio.sleep(0)
        return ExecResult(ok=True, n_points=12345)

    async def run_training(self, scene_id: UUID) -> ExecResult:  # noqa: ARG002
        await asyncio.sleep(0)
        return ExecResult(ok=True, n_gaussians=234_567, psnr_train=27.4)


# ---------------------------------------------------------------------------
# Pipeline orchestrator (thin — just walks the FSM using an Executor)
# ---------------------------------------------------------------------------


_DEFAULT_EXECUTOR: Executor = NoOpExecutor()


def get_executor() -> Executor:
    return _DEFAULT_EXECUTOR


def set_executor(ex: Executor) -> None:  # test hook + future DI
    global _DEFAULT_EXECUTOR
    _DEFAULT_EXECUTOR = ex


async def start_colmap(db: AsyncSession, scene: Scene) -> Scene:
    await transition(db, scene, "colmap")
    res = await get_executor().run_colmap(scene.id)
    if not res.ok:
        return await transition(db, scene, "failed", error_msg=res.error or "colmap failed")
    if res.n_points is not None:
        scene.n_points = res.n_points
    return await transition(db, scene, "colmap_done")


async def start_training(db: AsyncSession, scene: Scene) -> Scene:
    await transition(db, scene, "training")
    res = await get_executor().run_training(scene.id)
    if not res.ok:
        return await transition(db, scene, "failed", error_msg=res.error or "training failed")
    if res.n_gaussians is not None:
        scene.n_gaussians = res.n_gaussians
    if res.psnr_train is not None:
        scene.psnr_train = res.psnr_train
    return await transition(db, scene, "ready")


async def get_scene_or_404(db: AsyncSession, scene_id: UUID) -> Scene:
    from fastapi import HTTPException

    scene = (
        await db.execute(select(Scene).where(Scene.id == scene_id))
    ).scalar_one_or_none()
    if scene is None:
        raise HTTPException(404, f"scene {scene_id} not found")
    return scene
