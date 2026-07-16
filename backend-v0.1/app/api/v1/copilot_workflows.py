"""Copilot Workflow REST endpoints · v2.1 E2.1 · T10.3 + T10.5.

Stateless endpoints (T10.3):
    POST /copilot/workflows/validate       -- parse + static-check a DSL doc
    POST /copilot/workflows/run            -- parse + validate + execute

Persistence endpoints (T10.5, backed by ``copilot_workflows`` table):
    POST   /copilot/workflows              -- create a stored workflow
    GET    /copilot/workflows              -- list this org's workflows
    GET    /copilot/workflows/{id}         -- fetch by id
    PUT    /copilot/workflows/{id}         -- update (optimistic-lock via version)
    DELETE /copilot/workflows/{id}         -- soft-delete
    POST   /copilot/workflows/{id}/run     -- execute a stored workflow

Design rationale
----------------
* Optimistic lock via ``version``: every UPDATE requires the caller's
  ``version`` to match the row's current version, otherwise 409.
* Soft-delete (``deleted_at``) so run traces and audit records remain
  valid; the same name can be reused after delete because the unique
  index is partial on ``deleted_at IS NULL``.
* All persistence endpoints scope by ``org_id`` extracted from JWT.
  Cross-org access → 404 (never leak existence).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.copilot_workflow import CopilotWorkflow
from app.models.user import User
from app.services.tool_registry import ToolContext, build_default_registry
from app.services.workflow_dsl import (
    WorkflowError,
    WorkflowSemanticError,
    WorkflowSyntaxError,
    parse_workflow,
    topological_order,
    validate_workflow,
)
from app.services.workflow_executor import WorkflowExecutor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot/workflows", tags=["copilot-workflows"])


# =========================================================================== #
# Stateless (T10.3) schemas                                                   #
# =========================================================================== #


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_yaml: str | None = Field(None, max_length=64 * 1024)
    workflow: dict[str, Any] | None = None
    allowed_input_keys: list[str] | None = Field(None, max_length=64)


class ValidateResponse(BaseModel):
    ok: bool
    name: str | None = None
    steps: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error: str | None = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_yaml: str | None = Field(None, max_length=64 * 1024)
    workflow: dict[str, Any] | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    allowed_input_keys: list[str] | None = Field(None, max_length=64)


class RunStepResponse(BaseModel):
    id: str
    tool: str
    status: str
    resolved_args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0


class RunResponse(BaseModel):
    workflow_name: str
    status: str
    duration_ms: int
    steps: list[RunStepResponse]
    error: str | None = None


# =========================================================================== #
# Persistence (T10.5) schemas                                                 #
# =========================================================================== #


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=1024)
    dsl_yaml: str = Field(..., min_length=1, max_length=64 * 1024)


class WorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=1024)
    dsl_yaml: str | None = Field(None, min_length=1, max_length=64 * 1024)
    version: int = Field(
        ..., ge=1,
        description="Current version — write is rejected if stale.",
    )


class WorkflowRecordResponse(BaseModel):
    id: UUID
    name: str
    description: str
    dsl_yaml: str
    version: int
    owner_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class WorkflowRunStoredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, Any] = Field(default_factory=dict)
    allowed_input_keys: list[str] | None = Field(None, max_length=64)


# =========================================================================== #
# Helpers                                                                     #
# =========================================================================== #


def _pick_source(
    yaml_text: str | None, obj: dict[str, Any] | None
) -> str | dict[str, Any]:
    if yaml_text is not None and obj is not None:
        raise HTTPException(
            400, "provide exactly one of 'workflow_yaml' or 'workflow'"
        )
    if yaml_text is None and obj is None:
        raise HTTPException(
            400, "must provide either 'workflow_yaml' or 'workflow'"
        )
    return yaml_text if yaml_text is not None else obj  # type: ignore[return-value]


def _describe_error(exc: WorkflowError) -> tuple[str, str]:
    if isinstance(exc, WorkflowSyntaxError):
        return "syntax", str(exc)
    if isinstance(exc, WorkflowSemanticError):
        return "semantic", str(exc)
    return "workflow", str(exc)


def _to_record_response(row: CopilotWorkflow) -> WorkflowRecordResponse:
    return WorkflowRecordResponse(
        id=row.id, name=row.name, description=row.description,
        dsl_yaml=row.dsl_yaml, version=row.version,
        owner_user_id=row.owner_user_id,
        created_at=row.created_at, updated_at=row.updated_at,
    )


async def _load_alive(
    db: AsyncSession, wf_id: UUID, org_id: UUID | None
) -> CopilotWorkflow:
    """Fetch a workflow scoped to the caller's org, or 404."""
    row = (await db.execute(
        select(CopilotWorkflow).where(
            CopilotWorkflow.id == wf_id,
            CopilotWorkflow.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "workflow not found")
    if row.org_id != org_id:
        raise HTTPException(404, "workflow not found")
    return row


# =========================================================================== #
# Stateless endpoints (T10.3)                                                 #
# =========================================================================== #


@router.post("/validate", response_model=ValidateResponse)
async def validate_endpoint(
    body: ValidateRequest,
    user: User = Depends(get_current_user),
) -> ValidateResponse:
    src = _pick_source(body.workflow_yaml, body.workflow)
    try:
        doc = parse_workflow(src)
    except WorkflowError as e:
        etype, msg = _describe_error(e)
        return ValidateResponse(ok=False, error_type=etype, error=msg)

    registry = build_default_registry()
    allowed_keys = set(body.allowed_input_keys) if body.allowed_input_keys else None
    try:
        validate_workflow(doc, registry, allowed_input_keys=allowed_keys)
    except WorkflowError as e:
        etype, msg = _describe_error(e)
        return ValidateResponse(
            ok=False, error_type=etype, error=msg, name=doc.name
        )

    return ValidateResponse(
        ok=True, name=doc.name,
        steps=topological_order(doc.steps),
        tools_used=sorted({s.tool for s in doc.steps}),
    )


@router.post("/run", response_model=RunResponse)
async def run_endpoint(
    body: RunRequest,
    user: User = Depends(get_current_user),
) -> RunResponse:
    src = _pick_source(body.workflow_yaml, body.workflow)

    try:
        doc = parse_workflow(src)
    except WorkflowError as e:
        raise HTTPException(400, f"parse: {e}")

    registry = build_default_registry()
    allowed_keys = set(body.allowed_input_keys) if body.allowed_input_keys else None
    try:
        validate_workflow(doc, registry, allowed_input_keys=allowed_keys)
    except WorkflowError as e:
        raise HTTPException(400, f"validate: {e}")

    ctx = ToolContext(org_id=user.org_id, user_id=user.id)
    run = await WorkflowExecutor(registry).run(doc, inputs=body.inputs, ctx=ctx)

    return RunResponse(
        workflow_name=run.workflow_name, status=run.status,
        duration_ms=run.duration_ms,
        steps=[
            RunStepResponse(
                id=s.id, tool=s.tool, status=s.status,
                resolved_args=s.resolved_args, result=s.result,
                error=s.error, duration_ms=s.duration_ms,
            )
            for s in run.steps
        ],
        error=run.error,
    )


# =========================================================================== #
# Persistence endpoints (T10.5)                                               #
# =========================================================================== #


@router.post(
    "", response_model=WorkflowRecordResponse, status_code=201,
)
async def create_workflow(
    body: WorkflowCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRecordResponse:
    """Create a new stored workflow.

    The DSL is *statically validated* before insert — a bad workflow
    never lands in the DB.
    """
    # Validate DSL up-front — reject 400 before hitting DB.
    try:
        doc = parse_workflow(body.dsl_yaml)
        validate_workflow(doc, build_default_registry())
    except WorkflowError as e:
        etype, msg = _describe_error(e)
        raise HTTPException(400, f"{etype}: {msg}")

    row = CopilotWorkflow(
        org_id=user.org_id,
        owner_user_id=user.id,
        name=body.name,
        description=body.description,
        dsl_yaml=body.dsl_yaml,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        log.warning("workflow create IntegrityError: %s", e)
        raise HTTPException(
            409, f"a workflow named {body.name!r} already exists"
        )
    await db.refresh(row)
    return _to_record_response(row)


@router.get("", response_model=list[WorkflowRecordResponse])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkflowRecordResponse]:
    q = select(CopilotWorkflow).where(
        CopilotWorkflow.org_id == user.org_id,
        CopilotWorkflow.deleted_at.is_(None),
    ).order_by(CopilotWorkflow.updated_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_to_record_response(r) for r in rows]


@router.get("/{wf_id}", response_model=WorkflowRecordResponse)
async def get_workflow(
    wf_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRecordResponse:
    row = await _load_alive(db, wf_id, user.org_id)
    return _to_record_response(row)


@router.put("/{wf_id}", response_model=WorkflowRecordResponse)
async def update_workflow(
    wf_id: UUID,
    body: WorkflowUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRecordResponse:
    """Update a workflow with optimistic-lock via ``version``.

    * If ``body.version`` != row.version → 409 CONFLICT.
    * If ``dsl_yaml`` is present, it's re-validated before write.
    * Version is bumped by 1 on successful write.
    """
    row = await _load_alive(db, wf_id, user.org_id)
    if body.version != row.version:
        raise HTTPException(
            409,
            f"stale version: expected {row.version}, got {body.version}",
        )

    # Optional DSL revalidation before write.
    if body.dsl_yaml is not None:
        try:
            doc = parse_workflow(body.dsl_yaml)
            validate_workflow(doc, build_default_registry())
        except WorkflowError as e:
            etype, msg = _describe_error(e)
            raise HTTPException(400, f"{etype}: {msg}")

    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.dsl_yaml is not None:
        row.dsl_yaml = body.dsl_yaml
    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            409, f"a workflow named {row.name!r} already exists"
        )
    await db.refresh(row)
    return _to_record_response(row)


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(
    wf_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = await _load_alive(db, wf_id, user.org_id)
    row.deleted_at = datetime.utcnow()
    await db.commit()
    return None


@router.post("/{wf_id}/run", response_model=RunResponse)
async def run_stored_workflow(
    wf_id: UUID,
    body: WorkflowRunStoredRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunResponse:
    """Execute a previously-stored workflow.

    Revalidates the DSL at run time because the tool registry evolves
    independently — a workflow saved yesterday may reference a tool
    that's been removed today.
    """
    row = await _load_alive(db, wf_id, user.org_id)

    try:
        doc = parse_workflow(row.dsl_yaml)
    except WorkflowError as e:
        raise HTTPException(400, f"parse: {e}")

    registry = build_default_registry()
    allowed_keys = set(body.allowed_input_keys) if body.allowed_input_keys else None
    try:
        validate_workflow(doc, registry, allowed_input_keys=allowed_keys)
    except WorkflowError as e:
        raise HTTPException(400, f"validate: {e}")

    ctx = ToolContext(org_id=user.org_id, user_id=user.id)
    run = await WorkflowExecutor(registry).run(doc, inputs=body.inputs, ctx=ctx)

    return RunResponse(
        workflow_name=run.workflow_name, status=run.status,
        duration_ms=run.duration_ms,
        steps=[
            RunStepResponse(
                id=s.id, tool=s.tool, status=s.status,
                resolved_args=s.resolved_args, result=s.result,
                error=s.error, duration_ms=s.duration_ms,
            )
            for s in run.steps
        ],
        error=run.error,
    )


__all__ = ["router"]
