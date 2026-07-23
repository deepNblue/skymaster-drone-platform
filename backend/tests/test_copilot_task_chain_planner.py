"""E2.4b · Task Chain planner / reflector 单元测试.

不打真实 LLM — 用 monkeypatch 替换 LLMClient.chat_completion。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import copilot_task_chain_planner as planner_svc
from app.services.tool_registry import build_default_registry

pytestmark = pytest.mark.asyncio


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(
        self, *, messages: list[dict[str, Any]], model: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "model": model})
        return self.payload


def _anthropic_wrap(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


# ============ plan() ============

async def test_plan_happy() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "subtasks": [
            {
                "title": "列出无人机", "tool": "list_drones",
                "args": {}, "why": "先看当前机队",
            },
        ],
    }, ensure_ascii=False)))
    reg = build_default_registry()
    result = await planner_svc.plan(
        goal="看看无人机状态", llm=fake, registry=reg,  # type: ignore[arg-type]
    )
    assert len(result.subtasks) == 1
    assert result.subtasks[0]["tool"] == "list_drones"
    # System prompt must contain the tool catalog
    assert "list_drones" in fake.calls[0]["messages"][0]["content"]


async def test_plan_openai_format() -> None:
    fake = _FakeLLM({
        "choices": [{
            "message": {
                "content": json.dumps({
                    "subtasks": [{
                        "title": "s", "tool": "list_missions",
                        "args": {}, "why": "y",
                    }],
                }),
            },
        }],
    })
    reg = build_default_registry()
    result = await planner_svc.plan(
        goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
    )
    assert result.subtasks[0]["tool"] == "list_missions"


async def test_plan_markdown_fence_stripped() -> None:
    txt = "```json\n" + json.dumps({
        "subtasks": [{
            "title": "s", "tool": "list_drones", "args": {}, "why": "y",
        }],
    }) + "\n```"
    fake = _FakeLLM(_anthropic_wrap(txt))
    reg = build_default_registry()
    result = await planner_svc.plan(
        goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
    )
    assert result.subtasks[0]["tool"] == "list_drones"


async def test_plan_unknown_tool_rejected() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "subtasks": [
            {"title": "s", "tool": "nonexistent_x", "args": {}, "why": "y"},
        ],
    })))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="unknown tool"):
        await planner_svc.plan(
            goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
        )


async def test_plan_refusal() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "error": "no tool covers real-time weather",
    })))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="planner refused"):
        await planner_svc.plan(
            goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
        )


async def test_plan_bad_json() -> None:
    fake = _FakeLLM(_anthropic_wrap("this is not json"))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="no JSON"):
        await planner_svc.plan(
            goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
        )


async def test_plan_too_long() -> None:
    subs = [
        {"title": f"s{i}", "tool": "list_drones", "args": {}, "why": "y"}
        for i in range(9)
    ]
    fake = _FakeLLM(_anthropic_wrap(json.dumps({"subtasks": subs})))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="too long"):
        await planner_svc.plan(
            goal="g", llm=fake, registry=reg,  # type: ignore[arg-type]
        )


# ============ reflect() ============

async def test_reflect_replace_remaining() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "kind": "replace_remaining",
        "new_tail": [
            {"title": "重新执行", "tool": "list_drones",
             "args": {}, "why": "回退到已知可行"},
        ],
        "reason": "上一步失败，需要重试",
    })))
    reg = build_default_registry()
    sug = await planner_svc.reflect(
        goal="g", plan_json=[
            {"title": "s0", "tool": "list_drones", "args": {}, "why": ""},
        ],
        steps_summary=[{"step_index": 0, "tool": "list_drones",
                        "status": "failed", "error": "boom"}],
        trigger="step_failed",
        llm=fake, registry=reg,  # type: ignore[arg-type]
    )
    assert sug.kind == "replace_remaining"
    assert sug.new_tail and len(sug.new_tail) == 1
    assert "重试" in sug.reason


async def test_reflect_abort() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "kind": "abort",
        "reason": "无法通过现有工具达成",
    })))
    reg = build_default_registry()
    sug = await planner_svc.reflect(
        goal="g", plan_json=[], steps_summary=[],
        trigger="user_reflect",
        llm=fake, registry=reg,  # type: ignore[arg-type]
    )
    assert sug.kind == "abort"
    assert sug.new_tail is None


async def test_reflect_invalid_kind() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "kind": "nuke", "reason": "?",
    })))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="invalid kind"):
        await planner_svc.reflect(
            goal="g", plan_json=[], steps_summary=[],
            trigger="user_reflect",
            llm=fake, registry=reg,  # type: ignore[arg-type]
        )


async def test_reflect_missing_reason() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "kind": "mark_completed",
    })))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="missing reason"):
        await planner_svc.reflect(
            goal="g", plan_json=[], steps_summary=[],
            trigger="user_reflect",
            llm=fake, registry=reg,  # type: ignore[arg-type]
        )


async def test_reflect_new_tail_unknown_tool() -> None:
    fake = _FakeLLM(_anthropic_wrap(json.dumps({
        "kind": "append_step",
        "new_tail": [{"title": "s", "tool": "made_up",
                      "args": {}, "why": "y"}],
        "reason": "补一步",
    })))
    reg = build_default_registry()
    with pytest.raises(planner_svc.PlannerError, match="unknown tool"):
        await planner_svc.reflect(
            goal="g", plan_json=[], steps_summary=[],
            trigger="user_reflect",
            llm=fake, registry=reg,  # type: ignore[arg-type]
        )


# ============ summarize_steps ============

def test_summarize_steps() -> None:
    class _S:
        def __init__(self, i: int, out: Any, err: str | None = None) -> None:
            self.step_index = i
            self.tool = "list_drones"
            self.status = "succeeded" if err is None else "failed"
            self.output_json = out
            self.error = err
    xs = [_S(0, {"total": 3}), _S(1, None, "explosion")]
    out = planner_svc.summarize_steps(xs)
    assert len(out) == 2
    assert out[0]["step_index"] == 0
    assert "total" in out[0]["output_short"]
    assert out[1]["error"] == "explosion"


def test_summarize_steps_truncates_long_output() -> None:
    class _S:
        step_index = 0
        tool = "x"
        status = "succeeded"
        output_json = {"data": "x" * 5000}
        error = None
    out = planner_svc.summarize_steps([_S()])
    assert len(out[0]["output_short"]) <= 400
