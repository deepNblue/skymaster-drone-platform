"""Training-as-a-Service (TaaS) models — v2.3 E6.

Track E6: Training-as-a-Service — GPU cluster one-click fine-tuning.

Data model:
- `FineTuneJob` — one fine-tuning job = user upload data + base model + params + run on GPU pool
- `TrainingDataset` — uploaded dataset metadata + storage location
- `GPUNode` — registered GPU worker node
- `FineTuneMetric` — per-step metrics (loss/accuracy) for charting
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TrainingDataset(Base):
    """User uploaded dataset for fine-tuning.

    Storage format can be CSV / JSONL / ZIP / tar, depending on model type.
    Format checked on upload; schema validation performed before training start.
    """

    __tablename__ = "taas_training_datasets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="classification",
    )  # classification / object-detection / text-lm / diffusion
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)  # jsonl / csv / zip
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)  # s3:// / minio://
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_validation: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending",
    )  # pending / passed / failed
    schema_errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class GPUNode(Base):
    """Registered GPU compute node available for training.

    Nodes register themselves via heartbeat; scheduler picks based on:
    1. Availability (free VRAM > requested)
    2. Current load (least loaded first)
    3. Labels (match required CUDA version / GPU type)
    """

    __tablename__ = "taas_gpu_nodes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)  # hostname:port
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    gpu_model: Mapped[str] = mapped_column(String(64), nullable=False)  # RTX 3090 / A100 / ...
    total_vram_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    used_vram_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cuda_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    driver_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    labels: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class FineTuneJob(Base):
    """One fine-tuning job run on TaaS.

    State machine:
    ```
    draft -> queued -> scheduled -> running -> completed -> published
                          \-> failed
    ```
    """

    __tablename__ = "taas_fine_tune_jobs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Base model to fine-tune
    base_model_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_listings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    base_model_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taas_training_datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Training hyperparameters
    num_epochs: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    learning_rate: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False, default=5e-5)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    gradient_accumulation_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lora_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = full fine-tune
    max_seq_length: Mapped[int | None] = mapped_column(Integer, nullable=True)  # for LM

    # Output
    output_model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_model_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # logs/checkpoints
    final_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # final loss/accuracy etc

    # Scheduling
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft", index=True,
    )  # draft / queued / scheduled / running / completed / failed / canceled
    scheduled_node_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taas_gpu_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_vram_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Publishing
    published_to_marketplace: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    marketplace_model_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_listings.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Billing
    gpu_hours_used: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class FineTuneMetric(Base):
    """Per-step or per-epoch metrics for live plotting.

    Stored separately from FineTuneJob to avoid huge JSON blobs and allow
    incremental streaming to frontend.
    """

    __tablename__ = "taas_fine_tune_metrics"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taas_fine_tune_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loss: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    other_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
