"""Unit tests for Copilot Workflow DSL v0.1 (v2.1 Track E · T10.1)."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.services.tool_registry import ToolContext, ToolRegistry, ToolSpec
from app.services.workflow_dsl import (
    DSL_VERSION,
    WorkflowSemanticError,
    WorkflowSyntaxError,
    find_interpolations,
    parse_workflow,
    topological_order,
    validate_workflow,
)


# ------------------------------------------------------------------- #
# Test fixtures — a tiny local registry independent of prod tools.    #
# ------------------------------------------------------------------- #


class _EchoArgs(BaseModel):
    msg: str
    n: int = 1


class _SumArgs(BaseModel):
    values: list[int]


async def _echo_impl(ctx, args: _EchoArgs) -> dict[str, Any]:
    return {"echoed": args.msg * args.n}


async def _sum_impl(ctx, args: _SumArgs) -> dict[str, Any]:
    return {"sum": sum(args.values)}


def _mk_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolSpec(
        name="echo",
        description="echo msg N times",
        args_schema=_EchoArgs,
        func=_echo_impl,
        permission="readonly",
    ))
    r.register(ToolSpec(
        name="sum",
        description="sum a list of ints",
        args_schema=_SumArgs,
        func=_sum_impl,
        permission="readonly",
    ))
    return r


# =================================================================== parse =


def test_parse_yaml_happy():
    src = f"""
version: "{DSL_VERSION}"
name: "hello"
description: "trivial workflow"
steps:
  - id: s1
    tool: echo
    args:
      msg: "hi"
      n: 3
"""
    doc = parse_workflow(src)
    assert doc.name == "hello"
    assert len(doc.steps) == 1
    assert doc.steps[0].id == "s1"
    assert doc.steps[0].tool == "echo"


def test_parse_dict_input_ok():
    doc = parse_workflow({
        "version": DSL_VERSION,
        "name": "d",
        "steps": [{"id": "s", "tool": "echo", "args": {"msg": "x"}}],
    })
    assert doc.steps[0].id == "s"


def test_parse_rejects_malformed_yaml():
    with pytest.raises(WorkflowSyntaxError):
        parse_workflow("::not: yaml: at all: [unterminated")


def test_parse_rejects_extra_fields():
    src = f"""
version: "{DSL_VERSION}"
name: "x"
mystery_field: 42
steps:
  - id: s
    tool: echo
    args: {{ msg: "hi" }}
"""
    with pytest.raises(WorkflowSyntaxError):
        parse_workflow(src)


def test_parse_rejects_bad_step_id():
    """step id must be a valid identifier."""
    with pytest.raises(WorkflowSyntaxError):
        parse_workflow({
            "version": DSL_VERSION,
            "name": "n",
            "steps": [{"id": "9bad", "tool": "echo", "args": {"msg": "x"}}],
        })


def test_parse_rejects_empty_steps():
    with pytest.raises(WorkflowSyntaxError):
        parse_workflow({
            "version": DSL_VERSION, "name": "empty", "steps": [],
        })


def test_parse_rejects_root_scalar():
    with pytest.raises(WorkflowSyntaxError):
        parse_workflow("42")


# =========================================================== interpolation =


def test_find_interpolations_in_nested_args():
    args = {
        "top": "${input.scene_id}",
        "arr": ["static", "${steps.a.result.foo}"],
        "map": {"deep": {"leaf": "${steps.b.result.bar}"}},
        "mixed": "prefix-${input.other}-suffix",
    }
    refs = find_interpolations(args)
    raws = {r.raw for r in refs}
    assert raws == {
        "${input.scene_id}", "${steps.a.result.foo}",
        "${steps.b.result.bar}", "${input.other}",
    }
    step_refs = [r for r in refs if r.is_step_ref]
    assert {r.step_id for r in step_refs} == {"a", "b"}


def test_find_interpolations_ignores_non_matching_strings():
    args = {"x": "no dollar here", "y": 42}
    assert find_interpolations(args) == []


# ============================================================ topo & cycle =


def test_topological_order_simple_chain():
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "chain",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"}},
            {"id": "b", "tool": "echo", "args": {"msg": "2"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo", "args": {"msg": "3"},
             "depends_on": ["b"]},
        ],
    })
    assert topological_order(doc.steps) == ["a", "b", "c"]


def test_topological_order_diamond():
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "diamond",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"}},
            {"id": "b", "tool": "echo", "args": {"msg": "2"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo", "args": {"msg": "3"},
             "depends_on": ["a"]},
            {"id": "d", "tool": "echo", "args": {"msg": "4"},
             "depends_on": ["b", "c"]},
        ],
    })
    order = topological_order(doc.steps)
    assert order[0] == "a"
    assert order[-1] == "d"
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


# =============================================================== validate =


def test_validate_happy_path():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "ok",
        "steps": [
            {"id": "s1", "tool": "echo",
             "args": {"msg": "${input.greeting}", "n": 3}},
        ],
    })
    validate_workflow(doc, reg, allowed_input_keys={"greeting"})


def test_validate_wrong_dsl_version():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": "9.9", "name": "future",
        "steps": [{"id": "s", "tool": "echo", "args": {"msg": "x"}}],
    })
    with pytest.raises(WorkflowSemanticError, match="unsupported DSL"):
        validate_workflow(doc, reg)


def test_validate_unknown_tool():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [{"id": "s", "tool": "no_such_tool", "args": {}}],
    })
    with pytest.raises(WorkflowSemanticError, match="unknown tool"):
        validate_workflow(doc, reg)


def test_validate_bad_args_shape():
    reg = _mk_registry()
    # echo requires msg:str, we pass an int
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [{"id": "s", "tool": "echo", "args": {"msg": 42}}],
    })
    with pytest.raises(WorkflowSemanticError, match="args invalid"):
        validate_workflow(doc, reg)


def test_validate_args_with_interpolation_bypasses_type_check():
    """${input.x} is opaque at parse-time — validator must not choke on
    a placeholder being 'wrong type'."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "sum",
             "args": {"values": "${input.nums}"}},
        ],
    })
    # values is a list-typed field, but ${input.nums} is a whole-string
    # ref → sentinel → list schema still fails. This documents that
    # authors should nest interpolations *inside* a list literal:
    with pytest.raises(WorkflowSemanticError):
        validate_workflow(doc, reg, allowed_input_keys={"nums"})


def test_validate_duplicate_step_id():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "echo", "args": {"msg": "a"}},
            {"id": "s", "tool": "echo", "args": {"msg": "b"}},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="duplicate step id"):
        validate_workflow(doc, reg)


def test_validate_dangling_depends_on():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "echo", "args": {"msg": "x"},
             "depends_on": ["ghost"]},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="unknown step 'ghost'"):
        validate_workflow(doc, reg)


def test_validate_self_dependency():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "echo", "args": {"msg": "x"},
             "depends_on": ["s"]},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="itself"):
        validate_workflow(doc, reg)


def test_validate_cycle_detection():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"},
             "depends_on": ["c"]},
            {"id": "b", "tool": "echo", "args": {"msg": "2"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo", "args": {"msg": "3"},
             "depends_on": ["b"]},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="cycle"):
        validate_workflow(doc, reg)


def test_validate_ref_to_non_ancestor_rejected():
    """${steps.X.…} in step S must have X ∈ transitive depends_on(S).
    Otherwise the ref would be evaluated before X had run."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"}},
            {"id": "b", "tool": "echo",
             "args": {"msg": "${steps.a.result.echoed}"}},
             # b does NOT depend on a
        ],
    })
    with pytest.raises(WorkflowSemanticError,
                       match="not in its transitive depends_on"):
        validate_workflow(doc, reg)


def test_validate_ref_to_ancestor_accepted():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"}},
            {"id": "b", "tool": "echo",
             "args": {"msg": "${steps.a.result.echoed}"},
             "depends_on": ["a"]},
        ],
    })
    validate_workflow(doc, reg)


def test_validate_transitive_ancestor_accepted():
    """A → B → C, C refs steps.A.… should be OK (A is transitive ancestor)."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "1"}},
            {"id": "b", "tool": "echo", "args": {"msg": "2"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo",
             "args": {"msg": "${steps.a.result.echoed}"},
             "depends_on": ["b"]},
        ],
    })
    validate_workflow(doc, reg)


def test_validate_disallowed_input_key():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "echo",
             "args": {"msg": "${input.secret}"}},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="allowed inputs"):
        validate_workflow(doc, reg, allowed_input_keys={"greeting"})


def test_validate_unknown_scope_rejected():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "n",
        "steps": [
            {"id": "s", "tool": "echo",
             "args": {"msg": "${env.SECRET_KEY}"}},
        ],
    })
    with pytest.raises(WorkflowSemanticError, match="unknown ref scope"):
        validate_workflow(doc, reg)
