"""Unit tests for Copilot Workflow Executor v0.1 (v2.1 E2.1 · T10.2)."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.services.tool_registry import ToolContext, ToolRegistry, ToolSpec
from app.services.workflow_dsl import DSL_VERSION, parse_workflow
from app.services.workflow_executor import (
    STEP_FAILED,
    STEP_OK,
    STEP_SKIPPED,
    WorkflowExecutor,
    resolve_interpolations,
    InterpolationError,
    StepResult,
)


# ---------------------------------------------------------------- fixtures ==


class _EchoArgs(BaseModel):
    msg: str
    n: int = 1


class _SumArgs(BaseModel):
    values: list[int]


class _BoomArgs(BaseModel):
    fail: bool = True


async def _echo(ctx, a: _EchoArgs) -> dict[str, Any]:
    return {"echoed": a.msg * a.n}


async def _sum(ctx, a: _SumArgs) -> dict[str, Any]:
    return {"sum": sum(a.values), "count": len(a.values)}


async def _boom(ctx, a: _BoomArgs) -> dict[str, Any]:
    if a.fail:
        raise RuntimeError("kaboom")
    return {"ok": True}


class _BadArgs(BaseModel):
    pass


async def _returns_str(ctx, a: _BadArgs) -> Any:
    return "not-a-dict"


def _mk_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolSpec(
        name="echo", description="", args_schema=_EchoArgs, func=_echo,
    ))
    r.register(ToolSpec(
        name="sum", description="", args_schema=_SumArgs, func=_sum,
    ))
    r.register(ToolSpec(
        name="boom", description="", args_schema=_BoomArgs, func=_boom,
    ))
    r.register(ToolSpec(
        name="badret", description="", args_schema=_BadArgs, func=_returns_str,
    ))
    return r


# ============================================================ interpolation


def test_resolve_interp_whole_string_preserves_type():
    """Pure `${input.n}` must return the raw int, not str(3)."""
    out = resolve_interpolations(
        "${input.n}", inputs={"n": 3}, step_results={},
    )
    assert out == 3
    assert isinstance(out, int)


def test_resolve_interp_embedded_stringifies():
    out = resolve_interpolations(
        "hello-${input.who}-!",
        inputs={"who": "world"}, step_results={},
    )
    assert out == "hello-world-!"


def test_resolve_interp_nested_containers():
    sr = StepResult(id="s1", tool="echo", status=STEP_OK,
                    result={"foo": {"bar": [1, 2, 3]}})
    out = resolve_interpolations(
        {
            "top": "${input.x}",
            "list": ["static", "${steps.s1.result.foo.bar}"],
        },
        inputs={"x": 42},
        step_results={"s1": sr},
    )
    assert out == {"top": 42, "list": ["static", [1, 2, 3]]}


def test_resolve_interp_missing_input_key():
    with pytest.raises(InterpolationError, match="missing key 'x'"):
        resolve_interpolations(
            "${input.x}", inputs={}, step_results={},
        )


def test_resolve_interp_step_not_ok():
    sr = StepResult(id="s1", tool="echo", status=STEP_FAILED, error="boom")
    with pytest.raises(InterpolationError, match="status='failed'"):
        resolve_interpolations(
            "${steps.s1.result.echoed}",
            inputs={}, step_results={"s1": sr},
        )


def test_resolve_interp_step_not_run():
    with pytest.raises(InterpolationError, match="has not run"):
        resolve_interpolations(
            "${steps.ghost.result.foo}",
            inputs={}, step_results={},
        )


def test_resolve_interp_unknown_scope():
    with pytest.raises(InterpolationError, match="unknown scope"):
        resolve_interpolations(
            "${env.FOO}", inputs={}, step_results={},
        )


# ===================================================================== run =


async def test_run_single_step_happy():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "single",
        "steps": [{"id": "s1", "tool": "echo",
                   "args": {"msg": "hi", "n": 2}}],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK
    assert len(run.steps) == 1
    assert run.steps[0].status == STEP_OK
    assert run.steps[0].result == {"echoed": "hihi"}
    assert run.steps[0].duration_ms >= 0


async def test_run_chain_with_step_result_ref():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "chain",
        "steps": [
            {"id": "a", "tool": "echo",
             "args": {"msg": "ping", "n": 2}},
            {"id": "b", "tool": "echo",
             "args": {"msg": "${steps.a.result.echoed}", "n": 1},
             "depends_on": ["a"]},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK
    a, b = run.steps
    assert a.result == {"echoed": "pingping"}
    # b's resolved msg was pingping, echoed once → still pingping
    assert b.result == {"echoed": "pingping"}
    assert b.resolved_args == {"msg": "pingping", "n": 1}


async def test_run_diamond_ordering():
    """a → b, a → c, {b,c} → d."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "diamond",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "x"}},
            {"id": "b", "tool": "echo", "args": {"msg": "y"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo", "args": {"msg": "z"},
             "depends_on": ["a"]},
            {"id": "d", "tool": "sum",
             "args": {"values": [1, 2, 3]},
             "depends_on": ["b", "c"]},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK
    order = [s.id for s in run.steps]
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")
    assert run.step("d").result == {"sum": 6, "count": 3}


async def test_run_inputs_propagate():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "inp",
        "steps": [
            {"id": "s", "tool": "echo",
             "args": {"msg": "${input.greeting}", "n": 2}},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc, inputs={"greeting": "hey"})
    assert run.status == STEP_OK
    assert run.step("s").result == {"echoed": "heyhey"}


# ================================================================ failures =


async def test_run_short_circuits_on_tool_failure():
    """b depends on a; boom fails a → b must be marked skipped, not run."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "sc",
        "steps": [
            {"id": "a", "tool": "boom", "args": {"fail": True}},
            {"id": "b", "tool": "echo", "args": {"msg": "after"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo", "args": {"msg": "also after"},
             "depends_on": ["b"]},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_FAILED
    assert run.step("a").status == STEP_FAILED
    assert "kaboom" in (run.step("a").error or "")
    assert run.step("b").status == STEP_SKIPPED
    assert run.step("c").status == STEP_SKIPPED
    assert "step 'a' failed" in (run.error or "")


async def test_run_missing_input_key_reports_step_error():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "miss",
        "steps": [
            {"id": "s", "tool": "echo",
             "args": {"msg": "${input.missing_key}"}},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc, inputs={})
    assert run.status == STEP_FAILED
    assert run.step("s").status == STEP_FAILED
    assert "interpolation" in (run.step("s").error or "")


async def test_run_bad_return_shape_flagged():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "bad-ret",
        "steps": [{"id": "s", "tool": "badret", "args": {}}],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_FAILED
    assert "expected dict" in (run.step("s").error or "")


async def test_run_tool_arg_schema_violation_flagged():
    """Interp resolves to wrong type → args_schema fails at call time."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "wrong-type",
        "steps": [
            {"id": "s", "tool": "sum",
             "args": {"values": "${input.v}"}},
        ],
    })
    # v is a string, but sum wants list[int] → ValidationError from
    # pydantic surfaces as ToolInvocationError (wrapped).
    run = await WorkflowExecutor(reg).run(doc, inputs={"v": "not-a-list"})
    assert run.status == STEP_FAILED
    assert run.step("s").status == STEP_FAILED


async def test_run_transitive_ref_reads_earlier_step():
    """a → b → c; c reads steps.a.result — should still resolve."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "transitive",
        "steps": [
            {"id": "a", "tool": "echo", "args": {"msg": "x"}},
            {"id": "b", "tool": "echo", "args": {"msg": "y"},
             "depends_on": ["a"]},
            {"id": "c", "tool": "echo",
             "args": {"msg": "${steps.a.result.echoed}"},
             "depends_on": ["b"]},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK
    assert run.step("c").result == {"echoed": "x"}


async def test_run_duration_ms_populated():
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "dur",
        "steps": [{"id": "s", "tool": "echo", "args": {"msg": "x"}}],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.duration_ms >= 0
    assert run.step("s").duration_ms >= 0
    assert run.finished_at > run.started_at


async def test_run_ctx_passed_through_to_tool():
    """ToolContext handed to executor must reach the tool's ctx arg."""
    seen: dict = {}

    class _CtxSpyArgs(BaseModel):
        pass

    async def _spy(ctx: ToolContext, a: _CtxSpyArgs) -> dict:
        seen["org_id"] = ctx.org_id
        seen["user_id"] = ctx.user_id
        return {"seen": True}

    reg = _mk_registry()
    reg.register(ToolSpec(
        name="spy", description="", args_schema=_CtxSpyArgs, func=_spy,
    ))
    from uuid import uuid4
    ctx = ToolContext(org_id=uuid4(), user_id=uuid4())
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "ctx",
        "steps": [{"id": "s", "tool": "spy", "args": {}}],
    })
    run = await WorkflowExecutor(reg).run(doc, ctx=ctx)
    assert run.status == STEP_OK
    assert seen["org_id"] == ctx.org_id
    assert seen["user_id"] == ctx.user_id


# =========================================================================
#  T10.4 · on_failure semantics                                            #
# =========================================================================


async def test_on_failure_continue_keeps_run_alive():
    """Tolerated step failure -> run.status stays 'ok', trace records
    step as failed; a downstream sibling that does NOT depend on it
    keeps running."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "tol",
        "steps": [
            {"id": "a", "tool": "boom", "args": {"fail": True},
             "on_failure": "continue"},
            {"id": "b", "tool": "echo", "args": {"msg": "still-here"}},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK  # run itself stays green
    assert run.step("a").status == STEP_FAILED
    assert "kaboom" in (run.step("a").error or "")
    assert run.step("b").status == STEP_OK  # sibling completes


async def test_on_failure_continue_downstream_ref_still_fails_at_interp():
    """Even with `on_failure: continue`, a *dependent* step that reads
    `${steps.a.result.…}` must fail at interpolation time — we don't
    invent a result. That dependent's on_failure controls what happens
    next."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "tol-dep",
        "steps": [
            {"id": "a", "tool": "boom", "args": {"fail": True},
             "on_failure": "continue"},
            # b depends on a's result -> must interp-fail
            {"id": "b", "tool": "echo",
             "args": {"msg": "${steps.a.result.something}"},
             "depends_on": ["a"]},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    # b fails fatally (default on_failure="fail") -> run failed
    assert run.status == STEP_FAILED
    assert run.step("a").status == STEP_FAILED
    assert run.step("b").status == STEP_FAILED
    assert "interpolation" in (run.step("b").error or "")


async def test_on_failure_fail_default_short_circuits():
    """Reaffirm T10.2 semantics: absent `on_failure`, first failure is
    fatal and downstream pending steps -> SKIPPED."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "default-fail",
        "steps": [
            {"id": "a", "tool": "boom", "args": {"fail": True}},
            {"id": "b", "tool": "echo", "args": {"msg": "unreachable"}},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_FAILED
    assert run.step("a").status == STEP_FAILED
    assert run.step("b").status == STEP_SKIPPED


async def test_on_failure_continue_records_reason_but_not_run_error():
    """Tolerated failures MUST NOT bubble up as run.error — that field
    is reserved for fatal failures, so callers can rely on it."""
    reg = _mk_registry()
    doc = parse_workflow({
        "version": DSL_VERSION, "name": "no-bubble",
        "steps": [
            {"id": "a", "tool": "boom", "args": {"fail": True},
             "on_failure": "continue"},
        ],
    })
    run = await WorkflowExecutor(reg).run(doc)
    assert run.status == STEP_OK
    assert run.error is None  # <-- key invariant
    assert run.step("a").error and "kaboom" in run.step("a").error
