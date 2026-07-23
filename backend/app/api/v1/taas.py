"""Training-as-a-Service API endpoints — v2.3 E6 TaaS.

Implements:
- GET /taas/datasets — list my datasets
- POST /taas/datasets — create/upload new dataset
- GET /taas/datasets/{id} — get dataset metadata
- DELETE /taas/datasets/{id} — delete dataset
- GET /taas/gpu-nodes — list available nodes (admin only)
- GET /taas/jobs — list my fine-tune jobs
- POST /taas/jobs — create new fine-tune job
- GET /taas/jobs/{id} — get job status + metrics
- POST /taas/jobs/{id}/cancel — cancel queued/running job
- GET /taas/jobs/{id}/metrics — stream metrics for chart
- POST /taas/jobs/{id}/publish — publish finished job to marketplace
"""
from __future__ import annotations

from typing import Annotated, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.taas import (
    TrainingDataset,
    GPUNode,
    FineTuneJob,
    FineTuneMetric,
)
from app.models.user import User


router = APIRouter(prefix="/taas", tags=["training-as-a-service"])


# ---------- Schemas ---------------------------------------------------------

class TrainingDatasetOut(BaseModel):
    id: UUID
    orgId: Optional[UUID] = Field(alias="org_id")
    ownerId: Optional[UUID] = Field(alias="owner_id")
    name: str
    description: Optional[str]
    datasetType: str = Field(alias="dataset_type")
    fileFormat: str = Field(alias="file_format")
    storageUri: str = Field(alias="storage_uri")
    sizeBytes: Optional[int] = Field(alias="size_bytes")
    numSamples: Optional[int] = Field(alias="num_samples")
    schemaValidation: str = Field(alias="schema_validation")
    schemaErrors: Optional[dict] = Field(alias="schema_errors")
    createdAt: str = Field(alias="created_at")

    model_config = {"from_attributes": True}


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    description: Optional[str] = None
    dataset_type: str = Field(description="classification / object-detection / text-lm")
    file_format: str = Field(description="jsonl / csv / zip")
    size_bytes: Optional[int] = None
    num_samples: Optional[int] = None


class GPUModelOut(BaseModel):
    id: UUID
    name: str
    gpu_model: str = Field(alias="gpu_model")
    total_vram_bytes: int = Field(alias="total_vram_bytes")
    used_vram_bytes: int = Field(alias="used_vram_bytes")
    enabled: bool
    last_heartbeat_at: Optional[str] = Field(alias="last_heartbeat_at")

    model_config = {"from_attributes": True}


class CreateFineTuneRequest(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    description: Optional[str] = None
    base_model_id: Optional[UUID] = None
    base_model_uri: Optional[str] = None
    dataset_id: UUID
    num_epochs: int = Field(default=3, ge=1, le=100)
    learning_rate: float = Field(default=5e-5, gt=0)
    batch_size: int = Field(default=8, ge=1, le=128)
    gradient_accumulation_steps: int = Field(default=1, ge=1)
    lora_rank: Optional[int] = Field(None, description="Set for LoRA fine-tune")
    max_seq_length: Optional[int] = None
    output_model_name: Optional[str] = None


class FineTuneJobOut(BaseModel):
    id: UUID
    orgId: Optional[UUID] = Field(alias="org_id")
    ownerId: Optional[UUID] = Field(alias="owner_id")
    name: str
    description: Optional[str]
    baseModelId: Optional[UUID] = Field(alias="base_model_id")
    datasetId: UUID = Field(alias="dataset_id")
    numEpochs: int = Field(alias="num_epochs")
    learningRate: float = Field(alias="learning_rate")
    batchSize: int = Field(alias="batch_size")
    loraRank: Optional[int] = Field(alias="lora_rank")
    state: str
    scheduledNodeId: Optional[UUID] = Field(alias="scheduled_node_id")
    startedAt: Optional[str] = Field(alias="started_at")
    finishedAt: Optional[str] = Field(alias="finished_at")
    errorMessage: Optional[str] = Field(alias="error_message")
    outputModelUri: Optional[str] = Field(alias="output_model_uri")
    publishedToMarketplace: bool = Field(alias="published_to_marketplace")
    marketplaceModelId: Optional[UUID] = Field(alias="marketplace_model_id")
    gpu_hours_used: Optional[float]
    cost_cents: Optional[int]
    createdAt: str = Field(alias="created_at")

    model_config = {"from_attributes": True}


class FineTuneMetricOut(BaseModel):
    id: UUID
    jobId: UUID = Field(alias="job_id")
    step: int
    epoch: Optional[int]
    loss: Optional[float]
    accuracy: Optional[float]
    other_metrics: Optional[dict]
    timestamp: str

    model_config = {"from_attributes": True}


# ---------- Endpoints -------------------------------------------------------


@router.get("/datasets", response_model=List[TrainingDatasetOut])
async def list_my_datasets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[TrainingDatasetOut]:
    """List all datasets owned by current user."""
    query = (
        select(TrainingDataset)
        .where(TrainingDataset.owner_id == current_user.id)
        .order_by(desc(TrainingDataset.created_at))
    )
    result = await db.execute(query)
    items = result.scalars().all()
    return [TrainingDatasetOut.model_validate(d) for d in items]


@router.post("/datasets", response_model=TrainingDatasetOut)
async def create_dataset(
    req: CreateDatasetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrainingDatasetOut:
    """Create a new dataset entry (presigned upload URL to be added in v2.3.1)."""
    ds = TrainingDataset(
        org_id=current_user.org_id,
        owner_id=current_user.id,
        name=req.name,
        description=req.description,
        dataset_type=req.dataset_type,
        file_format=req.file_format,
        size_bytes=req.size_bytes,
        num_samples=req.num_samples,
        storage_uri="",  # to be filled after upload completion
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return TrainingDatasetOut.model_validate(ds)


@router.get("/datasets/{dataset_id}", response_model=TrainingDatasetOut)
async def get_dataset(
    dataset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrainingDatasetOut:
    """Get metadata for a specific dataset."""
    ds = (
        await db.execute(select(TrainingDataset).where(TrainingDataset.id == dataset_id))
    ).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    if ds.owner_id != current_user.id and current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")
    return TrainingDatasetOut.model_validate(ds)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a dataset (owner only)."""
    ds = (
        await db.execute(select(TrainingDataset).where(TrainingDataset.id == dataset_id))
    ).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    if ds.owner_id != current_user.id and current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")
    await db.delete(ds)
    await db.commit()


@router.get("/gpu-nodes", response_model=List[GPUModelOut])
async def list_gpu_nodes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[GPUModelOut]:
    """List enabled GPU nodes (admin only)."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "admin only")
    query = select(GPUNode).where(GPUNode.enabled == True).order_by(GPUNode.name)
    result = await db.execute(query)
    nodes = result.scalars().all()
    return [GPUModelOut.model_validate(n) for n in nodes]


@router.get("/jobs", response_model=List[FineTuneJobOut])
async def list_my_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[FineTuneJobOut]:
    """List all fine-tune jobs owned by current user."""
    query = (
        select(FineTuneJob)
        .where(FineTuneJob.owner_id == current_user.id)
        .order_by(desc(FineTuneJob.created_at))
    )
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [FineTuneJobOut.model_validate(j) for j in jobs]


@router.post("/jobs", response_model=FineTuneJobOut)
async def create_finetune_job(
    req: CreateFineTuneRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FineTuneJobOut:
    """Create a new fine-tuning job, enqueue it for scheduling."""
    # Verify dataset exists and user owns it
    ds = (
        await db.execute(
            select(TrainingDataset).where(TrainingDataset.id == req.dataset_id)
        )
    ).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, "dataset not found")
    if ds.owner_id != current_user.id:
        raise HTTPException(403, "you do not own this dataset")
    if ds.schema_validation != "passed":
        raise HTTPException(400, "dataset schema validation not passed")

    job = FineTuneJob(
        org_id=current_user.org_id,
        owner_id=current_user.id,
        name=req.name,
        description=req.description,
        base_model_id=req.base_model_id,
        base_model_uri=req.base_model_uri,
        dataset_id=req.dataset_id,
        num_epochs=req.num_epochs,
        learning_rate=req.learning_rate,
        batch_size=req.batch_size,
        gradient_accumulation_steps=req.gradient_accumulation_steps,
        lora_rank=req.lora_rank,
        max_seq_length=req.max_seq_length,
        output_model_name=req.output_model_name,
        state="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return FineTuneJobOut.model_validate(job)


@router.get("/jobs/{job_id}", response_model=FineTuneJobOut)
async def get_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FineTuneJobOut:
    """Get current job status and metadata."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job.owner_id != current_user.id and current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")
    return FineTuneJobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", status_code=200)
async def cancel_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Cancel a queued or running job."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job.owner_id != current_user.id and current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")
    if job.state in ("completed", "failed", "canceled"):
        raise HTTPException(400, f"cannot cancel job in state {job.state}")

    from datetime import datetime
    job.state = "canceled"
    job.finished_at = datetime.utcnow()
    await db.commit()
    return {"status": "canceled"}


@router.get("/jobs/{job_id}/metrics", response_model=List[FineTuneMetricOut])
async def get_job_metrics(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[FineTuneMetricOut]:
    """Get all accumulated metrics for a job (for frontend charting)."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job.owner_id != current_user.id and current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "not permitted")

    query = (
        select(FineTuneMetric)
        .where(FineTuneMetric.job_id == job_id)
        .order_by(FineTuneMetric.step.asc())
    )
    result = await db.execute(query)
    metrics = result.scalars().all()
    return [FineTuneMetricOut.model_validate(m) for m in metrics]


@router.post("/jobs/{job_id}/publish", response_model=dict[str, UUID | None])
async def publish_job_to_marketplace(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, UUID | None]:
    """Publish a completed fine-tuned model to Model Marketplace."""
    job = (
        await db.execute(select(FineTuneJob).where(FineTuneJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job.owner_id != current_user.id:
        raise HTTPException(403, "not permitted")
    if job.state != "completed":
        raise HTTPException(400, "can only publish completed jobs")
    if job.published_to_marketplace and job.marketplace_model_id is not None:
        # already published
        return {"model_id": job.marketplace_model_id}

    # TODO(v2.3.1): actually create the model listing in marketplace
    # For MVP: just mark published and return placeholder ID
    from app.models.model_marketplace import ModelListing
    listing = ModelListing(
        slug=f"taas-{job_id}",
        name=job.output_model_name or job.name,
        description=job.description or f"Fine-tuned model from SkyMaster TaaS job {job_id}",
        task="",  # TODO: infer from dataset type
        framework="pytorch",
        tags=[],
        visibility="public",
        owner_org_id=job.org_id,
        owner_user_id=job.owner_id,
        price_model="free" if job.cost_cents == 0 else "one-time",
        price_unit=job.cost_cents / 100 if job.cost_cents else None,
        is_featured=False,
    )
    db.add(listing)
    job.published_to_marketplace = True
    job.marketplace_model_id = listing.id
    await db.commit()
    return {"model_id": listing.id}
