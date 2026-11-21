"""TaaS GPU Node agent API endpoints — called by GPU worker nodes.

v2.3 E6.1 — node registration, heartbeat, claim job, report metrics.
These endpoints are authenticated with node API key.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_db as get_db_dep
from app.models.taas import GPUNode, FineTuneJob, FineTuneMetric
from app.services.taas_scheduler import assign_heartbeat


router = APIRouter(prefix="/taas-node", tags=["taas-node"])


# ---------- Schemas ---------------------------------------------------------

class HeartbeatRequest(BaseModel):
    used_vram_bytes: int = Field(description="Current used VRAM in bytes")


class HeartbeatResponse(BaseModel):
    ok: bool
    message: str = ""


class ClaimNextJobResponse(BaseModel):
    job_id: Optional[str]
    ok: bool


class ReportMetricsRequest(BaseModel):
    step: int
    epoch: Optional[int]
    loss: Optional[float]
    accuracy: Optional[float]
    other_metrics: Optional[dict] = None


class ReportFinishedRequest(BaseModel):
    success: bool
    output_model_uri: Optional[str]
    error_message: Optional[str]
    gpu_hours_used: float
    cost_cents: int


# ---------- Endpoints -------------------------------------------------------


@router.post("/{node_id}/heartbeat", response_model=HeartbeatResponse)
async def node_heartbeat(
    node_id: UUID,
    req: HeartbeatRequest,
    db: AsyncSession = Depends(get_db_dep),
) -> HeartbeatResponse:
    """Update node heartbeat and current VRAM usage. Called periodically by node agent."""
    ok = await assign_heartbeat(node_id, req.used_vram_bytes, db)
    if not ok:
        return HeartbeatResponse(ok=False, message="node not found")
    return HeartbeatResponse(ok=True)


@router.get("/{node_id}/claim-next", response_model=ClaimNextJobResponse)
async def claim_next_job(
    node_id: UUID,
    db: AsyncSession = Depends(get_db_dep),
) -> ClaimNextJobResponse:
    """Node asks for next scheduled job to run."""
    # Check node exists and is enabled
    node = (
        await db.execute(select(GPUNode).where(GPUNode.id == node_id))
    ).scalar_one_or_none()
    if node is None or not node.enabled:
        return ClaimNextJobResponse(ok=False, job_id=None)

    # Find first scheduled job assigned to this node
    job = (
        await db.execute(
            select(FineTuneJob)
            .where(
                FineTuneJob.scheduled_node_id == node_id,
                FineTuneJob.state == "scheduled",
            )
            .order_by(FineTuneJob.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if job is None:
        return ClaimNextJobResponse(ok=True, job_id=None)

    # Mark as running
    from datetime import datetime
    job.state = "running"
    job.started_at = datetime.utcnow()
    await db.commit()

    return ClaimNextJobResponse(ok=True, job_id=str(job.id))


@router.post("/jobs/{job_id}/metrics", status_code=201)
async def report_metrics(
    job_id: UUID,
    req: ReportMetricsRequest,
    db: AsyncSession = Depends(get_db_dep),
) -> dict[str, bool]:
    """Report training metrics (per step/epoch) from node. Stored for frontend chart."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None or job.state != "running":
        raise HTTPException(404, "job not found or not running")

    metric = FineTuneMetric(
        job_id=job_id,
        step=req.step,
        epoch=req.epoch,
        loss=req.loss,
        accuracy=req.accuracy,
        other_metrics=req.other_metrics,
    )
    db.add(metric)
    await db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/finished", status_code=200)
async def report_finished(
    job_id: UUID,
    req: ReportFinishedRequest,
    db: AsyncSession = Depends(get_db_dep),
) -> dict[str, bool]:
    """Report job finished (success or failure) from node."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job.state != "running":
        raise HTTPException(400, f"job not in running state: {job.state}")

    from datetime import datetime
    job.finished_at = datetime.utcnow()
    job.state = "completed" if req.success else "failed"
    job.output_model_uri = req.output_model_uri
    job.error_message = req.error_message
    job.gpu_hours_used = req.gpu_hours_used
    job.cost_cents = req.cost_cents
    await db.commit()

    # Free VRAM on node
    # Node will update after next heartbeat
    return {"ok": True}


@router.get("/nodes", response_model=list[dict])
async def list_nodes(
    db: AsyncSession = Depends(get_db_dep),
) -> list[dict]:
    """List all registered GPU nodes (admin only via API, skip auth for MVP)."""
    query = select(GPUNode).order_by(GPUNode.name)
    result = await db.execute(query)
    nodes = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "name": n.name,
            "gpu_model": n.gpu_model,
            "total_vram_bytes": n.total_vram_bytes,
            "used_vram_bytes": n.used_vram_bytes,
            "enabled": n.enabled,
            "last_heartbeat_at": n.last_heartbeat_at and n.last_heartbeat_at.isoformat(),
        }
        for n in nodes
    ]
