"""Workflow executor v0.1 · v2.1 E2.1 · T10.2.

Consumes a :class:`~app.services.workflow_dsl.WorkflowDoc` that has
already passed :func:`~app.services.workflow_dsl.validate_workflow`
and runs it against a :class:`~app.services.tool_registry.ToolRegistry`
in topological order.

Runtime model
=============
* One :class:`WorkflowRun` per invocation; owns the shared ``inputs``
  dict + a mutable ``step_results`` map keyed by step id.
* Sequential execution for v0.1 — parallel dispatch of independent
  branches lands in T10.4 once we have real perf data justifying the
  complexity (the KICKOFF risk register warns against premature
  parallelism).
* Every step wraps in a try/except; on failure we mark the run
  ``status='failed'`` and short-circuit remaining steps. Upstream
  successes stay committed, downstream steps are marked ``skipped``
  so the trace stays faithful.
* Interpolation is done at *call time* (right before the tool runs),
  not at parse time — so ``${steps.X.result.foo}`` picks up whatever
  X actually returned. Missing keys along the dotted path raise
  :class:`InterpolationError` and fail the step.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.tool_registry import ToolContext, ToolRegistry
from app.services.workflow_dsl import (
    WorkflowDoc,
    WorkflowStep,
    _INTERP_RE,
    topological_order,
)

log = logging.getLogger(__name__)


# =========================================================================== #
# Errors                                                                      #
# =========================================================================== #


class WorkflowRuntimeError(Exception):
    """Base class for runtime failures."""


class InterpolationError(WorkflowRuntimeError):
    """A ``${scope.a.b}`` reference could not be resolved at run time."""


class ToolInvocationError(WorkflowRuntimeError):
    """A tool call raised or returned an unusable payload."""


# =========================================================================== #
# Runtime types                                                                #
# =========================================================================== #


STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"


@dataclass
class StepResult:
    """Per-step outcome, safe to serialise into copilot_trace."""

    id: str
    tool: str
    status: str = STEP_PENDING
    resolved_args: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class WorkflowRun:
    """Aggregate execution state; returned to the caller for auditing."""

    workflow_name: str
    inputs: dict[str, Any]
    status: str = STEP_PENDING  # pending | running | ok | failed
    steps: list[StepResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str | None = None

    @property
    def duration_ms(self) -> int:
        if self.finished_at <= 0.0:
            return 0
        return int((self.finished_at - self.started_at) * 1000)

    def step(self, step_id: str) -> StepResult | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


# =========================================================================== #
# Interpolation                                                                #
# =========================================================================== #


def _lookup_dotted(root: Any, path: tuple[str, ...]) -> Any:
    """Walk ``path`` through nested dicts (and objects with attrs).

    Raises :class:`InterpolationError` on the first miss so the tool
    author gets a clear signal.
    """
    cur: Any = root
    for i, seg in enumerate(path):
        if isinstance(cur, dict):
            if seg not in cur:
                raise InterpolationError(
                    f"missing key {seg!r} in {'.'.join(path[:i]) or '<root>'} "
                    f"(available: {sorted(cur.keys())})"
                )
            cur = cur[seg]
        else:
            # Fall back to attribute access for objects like StepResult.
            if not hasattr(cur, seg):
                raise InterpolationError(
                    f"cannot resolve {seg!r} on non-dict "
                    f"{type(cur).__name__} at {'.'.join(path[:i]) or '<root>'}"
                )
            cur = getattr(cur, seg)
    return cur


def resolve_interpolations(
    value: Any,
    *,
    inputs: dict[str, Any],
    step_results: dict[str, StepResult],
) -> Any:
    """Deep-walk ``value``; substitute every ``${scope.a.b}`` at runtime.

    Two modes:
      * **Whole-string** ref (e.g. ``"${input.n}"``) → replaced with the
        raw Python value (may be int/list/dict etc.). This is critical
        for numeric args — a str-typed replacement would fail schema.
      * **Embedded** ref (``"prefix-${x}-suffix"``) → substring replaced
        with ``str(value)``.
    """
    if isinstance(value, str):
        stripped = value.strip()
        m_full = _INTERP_RE.fullmatch(stripped)
        if m_full and stripped == value:
            # Pure-ref case: allow non-string return.
            expr = m_full.group("expr")
            parts = expr.split(".")
            scope, path = parts[0], tuple(parts[1:])
            return _resolve_scope(scope, path, inputs, step_results)

        # Embedded refs: build result by substring substitution.
        out_parts: list[str] = []
        cur = 0
        for m in _INTERP_RE.finditer(value):
            out_parts.append(value[cur:m.start()])
            expr = m.group("expr")
            parts = expr.split(".")
            scope, path = parts[0], tuple(parts[1:])
            resolved = _resolve_scope(scope, path, inputs, step_results)
            out_parts.append(str(resolved))
            cur = m.end()
        out_parts.append(value[cur:])
        return "".join(out_parts) if len(out_parts) > 1 else value

    if isinstance(value, list):
        return [
            resolve_interpolations(v, inputs=inputs, step_results=step_results)
            for v in value
        ]
    if isinstance(value, dict):
        return {
            k: resolve_interpolations(
                v, inputs=inputs, step_results=step_results
            )
            for k, v in value.items()
        }
    return value


def _resolve_scope(
    scope: str,
    path: tuple[str, ...],
    inputs: dict[str, Any],
    step_results: dict[str, StepResult],
) -> Any:
    if scope == "input":
        if not path:
            raise InterpolationError("${input.…} needs at least one segment")
        return _lookup_dotted(inputs, path)
    if scope == "steps":
        # ${steps.X.result.foo} — path[0] = step id, path[1..] into StepResult
        if not path:
            raise InterpolationError("${steps.…} needs at least one segment")
        step_id = path[0]
        sr = step_results.get(step_id)
        if sr is None:
            raise InterpolationError(
                f"step {step_id!r} has not run yet (or does not exist)"
            )
        if sr.status != STEP_OK:
            raise InterpolationError(
                f"step {step_id!r} status={sr.status!r}; "
                f"cannot read its result"
            )
        return _lookup_dotted(sr, path[1:])
    raise InterpolationError(f"unknown scope {scope!r}")


# =========================================================================== #
# Executor                                                                    #
# =========================================================================== #


class WorkflowExecutor:
    """Runs a validated WorkflowDoc against a ToolRegistry.

    Kept intentionally small — no retry, no parallelism, no branching.
    Every runtime concern lives here so ``workflow_dsl`` stays a pure
    parser and stays reusable by future editors/renderers.
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def run(
        self,
        doc: WorkflowDoc,
        *,
        inputs: dict[str, Any] | None = None,
        ctx: ToolContext | None = None,
    ) -> WorkflowRun:
        inputs = inputs or {}
        ctx = ctx or ToolContext()
        run = WorkflowRun(
            workflow_name=doc.name,
            inputs=dict(inputs),
            status=STEP_RUNNING,
            started_at=time.monotonic(),
        )
        # Pre-populate one StepResult per step, in topo order, so
        # skipped steps still appear in the trace.
        order = topological_order(doc.steps)
        by_id: dict[str, WorkflowStep] = {s.id: s for s in doc.steps}
        for sid in order:
            run.steps.append(StepResult(id=sid, tool=by_id[sid].tool))
        results_by_id: dict[str, StepResult] = {s.id: s for s in run.steps}

        try:
            for sid in order:
                await self._exec_one(
                    step_def=by_id[sid],
                    sr=results_by_id[sid],
                    run=run,
                    results_by_id=results_by_id,
                    ctx=ctx,
                )
                if run.status == STEP_FAILED:
                    # Short-circuit: mark all downstream pending → skipped.
                    for other_id in order:
                        other = results_by_id[other_id]
                        if other.status == STEP_PENDING:
                            other.status = STEP_SKIPPED
                    break
            if run.status != STEP_FAILED:
                run.status = STEP_OK
        finally:
            run.finished_at = time.monotonic()

        return run

    async def _exec_one(
        self,
        *,
        step_def: WorkflowStep,
        sr: StepResult,
        run: WorkflowRun,
        results_by_id: dict[str, StepResult],
        ctx: ToolContext,
    ) -> None:
        # 1) Resolve interpolations in this step's args.
        sr.started_at = time.monotonic()
        sr.status = STEP_RUNNING
        try:
            sr.resolved_args = resolve_interpolations(
                step_def.args,
                inputs=run.inputs,
                step_results=results_by_id,
            )
        except InterpolationError as e:
            sr.status = STEP_FAILED
            sr.error = f"interpolation: {e}"
            sr.finished_at = time.monotonic()
            sr.duration_ms = int(
                (sr.finished_at - sr.started_at) * 1000
            )
            log.warning("workflow step %s interp failed: %s", sr.id, e)
            run.status = STEP_FAILED
            run.error = f"step {sr.id!r} failed: {sr.error}"
            return

        # 2) Dispatch via the registry — reuses args_schema validation.
        try:
            result = await self.registry.call(
                tool_name=step_def.tool,
                args=sr.resolved_args,
                ctx=ctx,
            )
        except Exception as e:  # noqa: BLE001 — user tool can raise anything
            sr.status = STEP_FAILED
            sr.error = f"tool: {type(e).__name__}: {e}"
            sr.finished_at = time.monotonic()
            sr.duration_ms = int(
                (sr.finished_at - sr.started_at) * 1000
            )
            log.exception(
                "workflow step %s tool %s raised", sr.id, step_def.tool
            )
            run.status = STEP_FAILED
            run.error = f"step {sr.id!r} failed: {sr.error}"
            return

        # 3) Success. Normalise result to a dict for downstream refs.
        if not isinstance(result, dict):
            sr.status = STEP_FAILED
            sr.error = (
                f"tool {step_def.tool!r} returned {type(result).__name__}, "
                f"expected dict"
            )
            sr.finished_at = time.monotonic()
            sr.duration_ms = int(
                (sr.finished_at - sr.started_at) * 1000
            )
            run.status = STEP_FAILED
            run.error = f"step {sr.id!r} failed: {sr.error}"
            return

        sr.result = result
        sr.status = STEP_OK
        sr.finished_at = time.monotonic()
        sr.duration_ms = int((sr.finished_at - sr.started_at) * 1000)


__all__ = [
    "InterpolationError",
    "StepResult",
    "ToolInvocationError",
    "WorkflowExecutor",
    "WorkflowRun",
    "WorkflowRuntimeError",
    "resolve_interpolations",
    "STEP_FAILED",
    "STEP_OK",
    "STEP_PENDING",
    "STEP_RUNNING",
    "STEP_SKIPPED",
]
