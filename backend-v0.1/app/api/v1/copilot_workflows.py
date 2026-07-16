"""Copilot Workflow REST endpoints · v2.1 E2.1 · T10.3.

Two stateless endpoints for v0.1 (no DB persistence yet — that lands in
T10.5 alongside an Alembic migration for a ``copilot_workflow`` table):

    POST /copilot/workflows/validate  --  parse + static-check a DSL doc
    POST /copilot/workflows/run       --  parse + validate + execute

Both accept YAML **or** JSON — YAML is what users author, JSON is what
frontends serialise. We detect which by looking at the ``content_type``
of the request; a ``workflow`` field in the JSON body wins for
compatibility.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.deps import get_current_user
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
# Request / response schemas                                                  #
# =========================================================================== #


class ValidateRequest(BaseModel):
    """Body for POST /copilot/workflows/validate.

    Exactly one of ``workflow_yaml`` or ``workflow`` must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_yaml: str | None = Field(
        None, max_length=64 * 1024,
        description="Workflow doc as raw YAML text.",
    )
    workflow: dict[str, Any] | None = Field(
        None, description="Workflow doc as a decoded JSON object.",
    )
    allowed_input_keys: list[str] | None = Field(
        None, max_length=64,
        description="If given, ${input.k} refs must use one of these keys.",
    )


class ValidateResponse(BaseModel):
    ok: bool
    name: str | None = None
    steps: list[str] = Field(default_factory=list, description="Topo-sorted step ids.")
    tools_used: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error: str | None = None


class RunRequest(BaseModel):
    """Body for POST /copilot/workflows/run.

    In addition to the DSL doc itself, callers pass a JSON dict of
    ``inputs`` which the workflow can consume via ``${input.foo}``.
    """

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
# Helpers                                                                     #
# =========================================================================== #


def _pick_source(
    yaml_text: str | None, obj: dict[str, Any] | None
) -> str | dict[str, Any]:
    """Reject if both/neither present; return the one provided."""
    if yaml_text is not None and obj is not None:
        raise HTTPException(
            400,
            "provide exactly one of 'workflow_yaml' or 'workflow'",
        )
    if yaml_text is None and obj is None:
        raise HTTPException(
            400,
            "must provide either 'workflow_yaml' or 'workflow'",
        )
    return yaml_text if yaml_text is not None else obj  # type: ignore[return-value]


def _describe_error(exc: WorkflowError) -> tuple[str, str]:
    if isinstance(exc, WorkflowSyntaxError):
        return "syntax", str(exc)
    if isinstance(exc, WorkflowSemanticError):
        return "semantic", str(exc)
    return "workflow", str(exc)


# =========================================================================== #
# Endpoints                                                                   #
# =========================================================================== #


@router.post("/validate", response_model=ValidateResponse)
async def validate_endpoint(
    body: ValidateRequest,
    user: User = Depends(get_current_user),
) -> ValidateResponse:
    """Parse + static-validate a workflow doc.

    Never executes any tool. Cheap (µs-scale) so safe to invoke on
    every keystroke from an editor UI.
    """
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
        ok=True,
        name=doc.name,
        steps=topological_order(doc.steps),
        tools_used=sorted({s.tool for s in doc.steps}),
    )


@router.post("/run", response_model=RunResponse)
async def run_endpoint(
    body: RunRequest,
    user: User = Depends(get_current_user),
) -> RunResponse:
    """One-shot: parse → static validate → execute.

    Returns the full ``WorkflowRun`` trace regardless of success. Failed
    workflows return **200** with ``status='failed'`` and per-step
    diagnostics — the HTTP-level 4xx is reserved for authoring errors
    (bad DSL, unknown tool) so the frontend can distinguish the two.
    """
    src = _pick_source(body.workflow_yaml, body.workflow)

    # 1) Parse
    try:
        doc = parse_workflow(src)
    except WorkflowError as e:
        raise HTTPException(400, f"parse: {e}")

    # 2) Static validation
    registry = build_default_registry()
    allowed_keys = set(body.allowed_input_keys) if body.allowed_input_keys else None
    try:
        validate_workflow(doc, registry, allowed_input_keys=allowed_keys)
    except WorkflowError as e:
        raise HTTPException(400, f"validate: {e}")

    # 3) Execute
    ctx = ToolContext(org_id=user.org_id, user_id=user.id)
    executor = WorkflowExecutor(registry)
    run = await executor.run(doc, inputs=body.inputs, ctx=ctx)

    return RunResponse(
        workflow_name=run.workflow_name,
        status=run.status,
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
