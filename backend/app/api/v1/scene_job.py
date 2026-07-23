"""REST API for scene job queue — v2.1 T2.3.

Two audiences:

* **Users / admin (control plane)**: enqueue, list, cancel, view.
* **Workers (data plane)**: claim / heartbeat / complete / fail.

Workers authenticate via a shared bearer token separate from user JWTs.
Set ``SKYMASTER_WORKER_TOKEN`` in env; default falls back to a random
per-process value that will reject all requests (fail-secure).
"""
from __future__ import annotations

import os
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.scene_job import SceneJob
from app.models.user import User
from app.services import scene_job as jobsvc


router = APIRouter(prefix="/scene-jobs", tags=["scene-jobs"])


_WORKER_TOKEN = os.environ.get("SKYMASTER_WORKER_TOKEN", f"noworker-{secrets.token_hex(8)}")


def _require_worker(x_worker_token: Optional[str] = Header(None)) -> None:
    if not x_worker_token or x_worker_token != _WORKER_TOKEN:
        raise HTTPException(401, "invalid worker token")


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) not in ("admin", "superadmin"):
        raise HTTPException(403, "admin-only endpoint")


def _map_err(e: jobsvc.JobError) -> HTTPException:
    s = str(e)
    if "not found" in s:
        return HTTPException(404, s)
    return HTTPException(400, s)


# ---------- schemas -------------------------------------------------------


class EnqueueBody(BaseModel):
    scene_id: UUID
    kind: str
    priority: int = 0


class JobOut(BaseModel):
    id: UUID
    scene_id: UUID
    kind: str
    status: str
    priority: int
    worker_id: Optional[str]
    attempts: int
    last_error: Optional[str]
    result_n_points: Optional[int]
    result_n_gaussians: Optional[int]
    result_psnr: Optional[float]

    class Config:
        from_attributes = True


class JobPage(BaseModel):
    total: int
    items: list[JobOut]


class ClaimBody(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    kinds: Optional[list[str]] = None
    lease_seconds: int = Field(300, ge=10, le=3600)


class HeartbeatBody(BaseModel):
    worker_id: str
    lease_seconds: int = 300
    running: bool = True


class CompleteBody(BaseModel):
    worker_id: str
    n_points: Optional[int] = None
    n_gaussians: Optional[int] = None
    psnr: Optional[float] = None


class FailBody(BaseModel):
    worker_id: str
    error: str = Field(..., min_length=1, max_length=4000)


class QueueStats(BaseModel):
    total: int
    by_kind: dict[str, dict[str, int]]


# ---------- control-plane endpoints --------------------------------------


@router.post("", response_model=JobOut, status_code=201)
async def enqueue(
    body: EnqueueBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    try:
        job = await jobsvc.enqueue(db, jobsvc.EnqueueParams(
            scene_id=body.scene_id, kind=body.kind, priority=body.priority,
        ))
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return job


@router.get("", response_model=JobPage)
async def list_jobs(
    status: Optional[str] = None,
    kind: Optional[str] = None,
    scene_id: Optional[UUID] = None,
    limit: int = 50, offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobPage:
    q = select(SceneJob)
    conds = []
    if status:
        conds.append(SceneJob.status == status)
    if kind:
        conds.append(SceneJob.kind == kind)
    if scene_id:
        conds.append(SceneJob.scene_id == scene_id)
    if conds:
        from sqlalchemy import and_
        q = q.where(and_(*conds))
    from sqlalchemy import func
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(
        q.order_by(SceneJob.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return JobPage(total=int(total), items=list(rows))


@router.get("/stats", response_model=QueueStats)
async def stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QueueStats:
    _require_admin(user)
    st = await jobsvc.queue_stats(db)
    return QueueStats(**st)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = (await db.execute(select(SceneJob).where(SceneJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    try:
        j = await jobsvc.cancel(db, job_id)
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return j


# ---------- worker-plane endpoints (bearer token auth) -------------------


@router.post("/_worker/claim", response_model=Optional[JobOut])
async def worker_claim(
    body: ClaimBody,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_worker),
) -> Optional[JobOut]:
    try:
        job = await jobsvc.claim_next(
            db, worker_id=body.worker_id,
            kinds=body.kinds, lease_seconds=body.lease_seconds,
        )
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return job


@router.post("/_worker/{job_id}/heartbeat", response_model=JobOut)
async def worker_heartbeat(
    job_id: UUID,
    body: HeartbeatBody,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_worker),
) -> JobOut:
    try:
        j = await jobsvc.heartbeat(
            db, job_id, body.worker_id,
            lease_seconds=body.lease_seconds, running=body.running,
        )
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return j


@router.post("/_worker/{job_id}/complete", response_model=JobOut)
async def worker_complete(
    job_id: UUID,
    body: CompleteBody,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_worker),
) -> JobOut:
    try:
        j = await jobsvc.complete(
            db, job_id, body.worker_id,
            result=jobsvc.CompleteParams(
                n_points=body.n_points,
                n_gaussians=body.n_gaussians,
                psnr=body.psnr,
            ),
        )
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return j


@router.post("/_worker/{job_id}/fail", response_model=JobOut)
async def worker_fail(
    job_id: UUID,
    body: FailBody,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_worker),
) -> JobOut:
    try:
        j = await jobsvc.fail(db, job_id, body.worker_id, error=body.error)
    except jobsvc.JobError as e:
        raise _map_err(e)
    await db.commit()
    return j
