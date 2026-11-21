"""Workflow DSL v0.1 · v2.1 Track E · E2.1 (T10.1).

User-defined Copilot workflows are declarative YAML/JSON documents that
chain N calls into the existing v2.0 Tool Registry. This module owns
*only* parsing + static validation; execution lives in
:mod:`app.services.workflow_executor` (T10.2).

Design rationale
================
* **Reuse over reinvention.** The DSL never introduces a new tool
  concept — every ``step`` targets a ``ToolSpec`` that's already
  registered via ``build_default_registry()``. This keeps the audit
  trail (permission, args_schema, function calling metadata) unified
  between L2 official playbooks and L3 user workflows.
* **Small on purpose.** v0.1 has 5 primitives: linear steps, string
  interpolation, ``depends_on`` DAG edges, cycle detection, args_schema
  validation. Advanced features (branch, loop, sub-workflow) are
  deferred until we have real user demand — the KICKOFF risk register
  explicitly warns against over-engineering.
* **Static-first.** All validation happens at parse-time so a bad
  workflow never reaches the runtime — a doubly important property
  when workflows may contain ``permission="sensitive"`` tool calls.

DSL surface (v0.1)
==================
::

    version: "0.1"
    name: "3dgs-quick-check"
    description: "Sample a scene, run vision qa, alert if fail."
    steps:
      - id: sample
        tool: scene_sample_thumbnails
        args:
          scene_id: "${input.scene_id}"
          n: 4
      - id: qa
        tool: vision_quality_check
        depends_on: [sample]
        args:
          image_urls: "${steps.sample.result.urls}"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.tool_registry import ToolRegistry


DSL_VERSION = "0.1"


# =========================================================================== #
# Schema                                                                      #
# =========================================================================== #


class WorkflowStep(BaseModel):
    """One node in a workflow DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64,
                    pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    tool: str = Field(..., min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    on_failure: Literal["fail", "continue"] = Field(
        default="fail",
        description=(
            "Controls short-circuit behaviour when this step fails. "
            "'fail' (default): mark the run failed and skip downstream "
            "pending steps. 'continue': record the step as failed but "
            "keep the run going. Descendants that reference this step's "
            "result still fail at interp time — safety over aggression."
        ),
    )


class WorkflowDoc(BaseModel):
    """Top-level workflow document."""

    model_config = ConfigDict(extra="forbid")

    version: str
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=1024)
    steps: list[WorkflowStep] = Field(..., min_length=1, max_length=64)


# =========================================================================== #
# Errors                                                                      #
# =========================================================================== #


class WorkflowError(Exception):
    """Any DSL parse/validation error."""


class WorkflowSyntaxError(WorkflowError):
    """Malformed YAML/JSON or schema violation."""


class WorkflowSemanticError(WorkflowError):
    """Structurally valid but semantically broken (cycle, dangling ref, …)."""


# =========================================================================== #
# Interpolation                                                               #
# =========================================================================== #


# ``${input.foo.bar}`` or ``${steps.step_id.result.key}`` — a top-level
# scope (``input`` / ``steps``) followed by 1..N dot segments.
_INTERP_RE = re.compile(
    r"\$\{(?P<expr>[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\}"
)


@dataclass
class InterpolationRef:
    """One parsed ``${scope.a.b.c}`` reference."""

    scope: str            # "input" | "steps"
    path: tuple[str, ...] # e.g. ("sample","result","urls") or ("scene_id",)
    raw: str              # the full "${...}" text

    @property
    def is_step_ref(self) -> bool:
        return self.scope == "steps"

    @property
    def step_id(self) -> str | None:
        return self.path[0] if self.is_step_ref and self.path else None


def find_interpolations(value: Any) -> list[InterpolationRef]:
    """Walk an arbitrary JSON-shape ``value`` and collect every ``${...}``
    reference we find inside string leaves."""
    refs: list[InterpolationRef] = []

    def _walk(v: Any) -> None:
        if isinstance(v, str):
            for m in _INTERP_RE.finditer(v):
                expr = m.group("expr")
                parts = expr.split(".")
                scope, path = parts[0], tuple(parts[1:])
                refs.append(
                    InterpolationRef(scope=scope, path=path, raw=m.group(0))
                )
        elif isinstance(v, list):
            for x in v:
                _walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)

    _walk(value)
    return refs


# =========================================================================== #
# Parser                                                                      #
# =========================================================================== #


def parse_workflow(source: str | Mapping[str, Any]) -> WorkflowDoc:
    """Parse a workflow from raw YAML/JSON text or an already-decoded dict.

    Raises :class:`WorkflowSyntaxError` on any schema violation.
    """
    if isinstance(source, str):
        try:
            data = yaml.safe_load(source)
        except yaml.YAMLError as e:
            raise WorkflowSyntaxError(f"YAML parse error: {e}") from e
    else:
        data = dict(source)

    if not isinstance(data, dict):
        raise WorkflowSyntaxError(
            f"workflow root must be a mapping, got {type(data).__name__}"
        )

    try:
        return WorkflowDoc.model_validate(data)
    except ValidationError as e:
        # Compact one-line messages — pydantic default is a bit noisy.
        msgs = [
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors()
        ]
        raise WorkflowSyntaxError("; ".join(msgs)) from e


# =========================================================================== #
# Semantic validation                                                          #
# =========================================================================== #


def _detect_cycle(
    steps: list[WorkflowStep],
) -> list[str] | None:
    """Return the list of step ids on the first cycle we find, else None.

    Uses a colour-marking DFS: white (unseen) → grey (on stack) → black
    (finished). Hitting a grey node = cycle.
    """
    by_id: dict[str, WorkflowStep] = {s.id: s for s in steps}
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {sid: WHITE for sid in by_id}
    parent: dict[str, str | None] = {sid: None for sid in by_id}

    def _dfs(u: str) -> list[str] | None:
        colour[u] = GREY
        for v in by_id[u].depends_on:
            if v not in by_id:
                continue  # dangling ref is caught elsewhere
            if colour[v] == GREY:
                # Reconstruct cycle: walk parents from u back to v.
                cyc = [v, u]
                cur = parent[u]
                while cur is not None and cur != v:
                    cyc.append(cur)
                    cur = parent[cur]
                cyc.append(v)
                return list(reversed(cyc))
            if colour[v] == WHITE:
                parent[v] = u
                c = _dfs(v)
                if c is not None:
                    return c
        colour[u] = BLACK
        return None

    for sid in by_id:
        if colour[sid] == WHITE:
            c = _dfs(sid)
            if c:
                return c
    return None


def topological_order(steps: list[WorkflowStep]) -> list[str]:
    """Return step ids in dependency-safe execution order.

    Assumes :func:`validate_workflow` has already run — no cycles, all
    ``depends_on`` refs known.
    """
    by_id: dict[str, WorkflowStep] = {s.id: s for s in steps}
    indeg: dict[str, int] = {s.id: len(s.depends_on) for s in steps}
    # Preserve authoring order among ready nodes → deterministic runs.
    queue: list[str] = [s.id for s in steps if indeg[s.id] == 0]
    order: list[str] = []
    while queue:
        u = queue.pop(0)
        order.append(u)
        # Any step that depends on u — decrement its indeg.
        for s in steps:
            if u in s.depends_on:
                indeg[s.id] -= 1
                if indeg[s.id] == 0:
                    queue.append(s.id)
    return order


def validate_workflow(
    doc: WorkflowDoc,
    registry: ToolRegistry,
    *,
    allowed_input_keys: set[str] | None = None,
) -> None:
    """Full semantic validation. Raises :class:`WorkflowSemanticError`
    with a compact message on the first violation.

    Checks:
      1. version string matches ``DSL_VERSION`` (soft compat surface).
      2. Every step ``id`` is unique.
      3. Every ``tool`` is registered.
      4. Args validate against the tool's ``args_schema`` *ignoring*
         ``${...}`` placeholders (we can't know their runtime type at
         parse time, so we replace them with a schema-friendly sentinel).
      5. Every ``depends_on`` refers to a real step.
      6. No cycles in the depends_on DAG.
      7. Every ``${steps.X.…}`` refers to a step that will execute
         *strictly before* the current step (i.e. transitive
         ``depends_on``).
      8. If ``allowed_input_keys`` is given, every ``${input.k}`` must
         use one of those keys.
    """
    if doc.version != DSL_VERSION:
        raise WorkflowSemanticError(
            f"unsupported DSL version {doc.version!r}, need {DSL_VERSION!r}"
        )

    # (2) unique ids
    seen: set[str] = set()
    for s in doc.steps:
        if s.id in seen:
            raise WorkflowSemanticError(f"duplicate step id: {s.id!r}")
        seen.add(s.id)

    # (3) known tools & (4) args_schema pre-check.
    known_tools = set(registry.names())
    for s in doc.steps:
        if s.tool not in known_tools:
            raise WorkflowSemanticError(
                f"step {s.id!r}: unknown tool {s.tool!r}"
            )
        spec = registry._tools[s.tool]  # noqa: SLF001 — introspection needed
        placeholder_args = _strip_interpolations_for_schema_check(s.args)
        try:
            spec.args_schema.model_validate(placeholder_args)
        except ValidationError as e:
            msgs = [
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
            raise WorkflowSemanticError(
                f"step {s.id!r} args invalid for tool {s.tool!r}: "
                + "; ".join(msgs)
            )

    # (5) depends_on refs exist
    for s in doc.steps:
        for d in s.depends_on:
            if d not in seen:
                raise WorkflowSemanticError(
                    f"step {s.id!r} depends on unknown step {d!r}"
                )
            if d == s.id:
                raise WorkflowSemanticError(
                    f"step {s.id!r} depends on itself"
                )

    # (6) cycle detection
    cyc = _detect_cycle(doc.steps)
    if cyc is not None:
        raise WorkflowSemanticError(
            f"dependency cycle detected: {' -> '.join(cyc)}"
        )

    # (7) interpolation reachability — collect for each step the set of
    # ancestors (transitive depends_on). A ${steps.X.…} in step S is
    # only valid when X ∈ ancestors(S).
    ancestors: dict[str, set[str]] = {}
    order = topological_order(doc.steps)
    by_id: dict[str, WorkflowStep] = {s.id: s for s in doc.steps}
    for sid in order:
        a: set[str] = set()
        for d in by_id[sid].depends_on:
            a.add(d)
            a.update(ancestors.get(d, set()))
        ancestors[sid] = a

    for s in doc.steps:
        for ref in find_interpolations(s.args):
            if ref.scope == "steps":
                target = ref.step_id
                if target is None:
                    raise WorkflowSemanticError(
                        f"step {s.id!r}: malformed ref {ref.raw}"
                    )
                if target not in seen:
                    raise WorkflowSemanticError(
                        f"step {s.id!r}: ref to unknown step {target!r}"
                    )
                if target not in ancestors[s.id]:
                    raise WorkflowSemanticError(
                        f"step {s.id!r}: uses ${{steps.{target}.…}} but "
                        f"{target!r} is not in its transitive depends_on"
                    )
            elif ref.scope == "input":
                if allowed_input_keys is not None:
                    key = ref.path[0] if ref.path else None
                    if key is None or key not in allowed_input_keys:
                        raise WorkflowSemanticError(
                            f"step {s.id!r}: ${{input.{key}}} is not in "
                            f"allowed inputs {sorted(allowed_input_keys)}"
                        )
            else:
                raise WorkflowSemanticError(
                    f"step {s.id!r}: unknown ref scope {ref.scope!r}"
                )


# =========================================================================== #
# Helpers                                                                      #
# =========================================================================== #


_SENTINEL = "__WF_INTERP__"


def _strip_interpolations_for_schema_check(value: Any) -> Any:
    """Replace every string containing ``${...}`` with a stable sentinel
    so pydantic doesn't complain about "expected int, got '${x}'".

    We *only* rewrite strings whose entire body is a single ``${…}`` —
    partial substitutions like ``"prefix-${x}-suffix"`` remain intact
    (they're still a valid str for the schema check).
    """
    if isinstance(value, str):
        if _INTERP_RE.fullmatch(value.strip()):
            # Whole-string ref → replace with sentinel str. Downstream
            # schemas that require int/float will still fail — which is
            # what we want (author has a type mismatch). But the pure
            # str case is now clean.
            return _SENTINEL
        return value
    if isinstance(value, list):
        return [_strip_interpolations_for_schema_check(x) for x in value]
    if isinstance(value, dict):
        return {
            k: _strip_interpolations_for_schema_check(v)
            for k, v in value.items()
        }
    return value


__all__ = [
    "DSL_VERSION",
    "WorkflowDoc",
    "WorkflowStep",
    "WorkflowError",
    "WorkflowSyntaxError",
    "WorkflowSemanticError",
    "InterpolationRef",
    "parse_workflow",
    "find_interpolations",
    "topological_order",
    "validate_workflow",
]
