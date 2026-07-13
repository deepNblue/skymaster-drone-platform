"""Copilot Agent v2 (T4.0) tests — Function Calling tool loop."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.copilot_agent_v2 import (
    AgentConfig,
    CopilotAgentV2,
    ToolCall,
    _parse_llm_response,
)
from app.services.tool_registry import (
    ToolContext,
    build_default_registry,
)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_anthropic_text_only():
    resp = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Hi there"}],
    }
    turn = _parse_llm_response(resp)
    assert turn.text == "Hi there"
    assert turn.tool_calls == []
    assert turn.stop_reason == "end_turn"
    assert not turn.wants_tools


def test_parse_anthropic_tool_use():
    resp = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "let me check"},
            {"type": "tool_use", "id": "toolu_1", "name": "list_drones", "input": {}},
        ],
    }
    turn = _parse_llm_response(resp)
    assert turn.text == "let me check"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "list_drones"
    assert turn.tool_calls[0].id == "toolu_1"
    assert turn.stop_reason == "tool_use"


def test_parse_openai_tool_use():
    resp = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {
                        "name": "get_drone_status",
                        "arguments": '{"drone_id": "abc"}',
                    },
                }],
            },
        }],
    }
    turn = _parse_llm_response(resp)
    assert turn.tool_calls[0].name == "get_drone_status"
    assert turn.tool_calls[0].arguments == {"drone_id": "abc"}
    assert turn.stop_reason == "tool_use"


def test_parse_openai_text_only():
    resp = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": "done", "tool_calls": []},
        }],
    }
    turn = _parse_llm_response(resp)
    assert turn.text == "done"
    assert turn.stop_reason == "stop"


def test_parse_malformed_returns_error():
    turn = _parse_llm_response({"weird": "shape"})
    assert turn.stop_reason == "error"


# ---------------------------------------------------------------------------
# Agent loop — anthropic protocol
# ---------------------------------------------------------------------------


def _make_llm(*responses: dict) -> AsyncMock:
    """Build a fake LLM that returns each response in sequence."""
    llm = AsyncMock()
    llm.protocol = "anthropic"
    llm.chat_completion = AsyncMock(side_effect=list(responses))
    return llm


class _EmitRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, ev: dict) -> None:
        self.events.append(ev)


@pytest.mark.asyncio
async def test_agent_answers_without_tools():
    llm = _make_llm({
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "无人机A当前正常"}],
    })
    reg = build_default_registry()
    agent = CopilotAgentV2(llm, reg)
    rec = _EmitRecorder()

    result = await agent.run(
        "帮我看下无人机A", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["text"] == "无人机A当前正常"
    assert result["tool_calls"] == []
    assert result["stopped_reason"] == "end"
    assert llm.chat_completion.call_count == 1


@pytest.mark.asyncio
async def test_agent_calls_readonly_tool_then_answers():
    """Full tool loop: LLM asks for list_drones, we run it, LLM synthesizes."""
    llm = _make_llm(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "list_drones", "input": {}},
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "你有 0 架无人机"}],
        },
    )
    reg = build_default_registry()
    agent = CopilotAgentV2(llm, reg)
    rec = _EmitRecorder()

    result = await agent.run(
        "列出所有无人机", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["text"] == "你有 0 架无人机"
    assert result["tool_calls"] == ["list_drones"]
    assert llm.chat_completion.call_count == 2
    # Second call must include the tool_result message
    second_call_args = llm.chat_completion.call_args_list[1]
    msgs = second_call_args.kwargs["messages"]
    assert any(
        m["role"] == "user"
        and isinstance(m["content"], list)
        and any(c.get("type") == "tool_result" for c in m["content"])
        for m in msgs
    )


@pytest.mark.asyncio
async def test_agent_sensitive_tool_enqueues_approval_and_stops():
    """create_mission should NOT execute — it should stash an approval and stop."""
    llm = _make_llm({
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": "t1", "name": "create_mission",
             "input": {"name": "巡逻", "drone_id": str(uuid4()),
                       "waypoints": [[104.06, 30.67, 100]]}},
        ],
    })
    reg = build_default_registry()
    agent = CopilotAgentV2(llm, reg)
    rec = _EmitRecorder()

    result = await agent.run(
        "创建一个巡逻任务", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "approval_required"
    assert len(result["pending_approvals"]) == 1
    # tool_calls list ONLY records actually-executed tools; sensitive is deferred
    assert "create_mission" not in result["tool_calls"]
    # SSE emitted approval_required event
    kinds = [e["type"] for e in rec.events]
    assert "approval_required" in kinds


@pytest.mark.asyncio
async def test_agent_tool_error_is_surfaced_to_llm():
    """A tool that raises should surface a tool_error, not abort the loop."""
    llm = _make_llm(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "get_drone_status",
                 "input": {"drone_id": "not-a-uuid"}},
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "无法识别的无人机ID"}],
        },
    )
    reg = build_default_registry()
    agent = CopilotAgentV2(llm, reg)
    rec = _EmitRecorder()

    result = await agent.run(
        "查询无人机", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "end"
    assert result["text"].startswith("无法")


@pytest.mark.asyncio
async def test_agent_unknown_tool_surfaced_as_error_result():
    llm = _make_llm(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "nonexistent_tool", "input": {}},
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "我不能这么做"}],
        },
    )
    agent = CopilotAgentV2(llm, build_default_registry())
    rec = _EmitRecorder()
    result = await agent.run(
        "调用未知工具", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "end"
    # unknown tool did not enter tool_calls (it's an error)
    assert result["tool_calls"] == []
    tool_events = [e for e in rec.events if e["type"] == "tool" and e["data"].get("event") == "error"]
    assert any(e["data"]["name"] == "nonexistent_tool" for e in tool_events)


@pytest.mark.asyncio
async def test_agent_respects_step_budget():
    """LLM in infinite tool-use loop should get cut off at max_tool_steps."""
    infinite_response = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": "loop", "name": "list_drones", "input": {}},
        ],
    }
    llm = AsyncMock()
    llm.protocol = "anthropic"
    llm.chat_completion = AsyncMock(return_value=infinite_response)

    agent = CopilotAgentV2(llm, build_default_registry(), AgentConfig(max_tool_steps=3))
    rec = _EmitRecorder()

    result = await agent.run(
        "无限循环", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "step_budget"
    # Should have called LLM at most max_tool_steps+1 times
    assert llm.chat_completion.call_count <= 4


@pytest.mark.asyncio
async def test_agent_handles_llm_timeout():
    async def slow(*a, **kw):
        await asyncio.sleep(5)
        return {}
    llm = AsyncMock()
    llm.protocol = "anthropic"
    llm.chat_completion = slow

    agent = CopilotAgentV2(
        llm, build_default_registry(), AgentConfig(per_turn_timeout=0.1),
    )
    rec = _EmitRecorder()
    result = await agent.run(
        "慢查询", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "timeout"
    kinds = [(e["type"], e["data"].get("stage")) for e in rec.events if e["type"] == "error"]
    assert any(stage == "llm_call" for _, stage in kinds)


@pytest.mark.asyncio
async def test_agent_handles_llm_exception():
    llm = AsyncMock()
    llm.protocol = "anthropic"
    llm.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
    agent = CopilotAgentV2(llm, build_default_registry())
    rec = _EmitRecorder()
    result = await agent.run(
        "触发异常", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "llm_error"


# ---------------------------------------------------------------------------
# Provider-agnostic: same agent works with OpenAI shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_works_with_openai_protocol():
    llm = AsyncMock()
    llm.protocol = "openai"
    llm.chat_completion = AsyncMock(side_effect=[
        {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "list_drones", "arguments": "{}"},
                    }],
                },
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "OK", "tool_calls": []},
            }],
        },
    ])

    agent = CopilotAgentV2(llm, build_default_registry())
    rec = _EmitRecorder()
    result = await agent.run(
        "列出无人机", history=None, ctx=ToolContext(),
        emit_cb=rec, session_id=uuid4(),
    )
    assert result["stopped_reason"] == "end"
    assert result["tool_calls"] == ["list_drones"]

    # 2nd request must contain the openai-style tool message
    msgs = llm.chat_completion.call_args_list[1].kwargs["messages"]
    assert any(m["role"] == "tool" for m in msgs)


# ---------------------------------------------------------------------------
# Sensitive-tool registration sanity
# ---------------------------------------------------------------------------


def test_default_registry_has_sensitive_tools():
    reg = build_default_registry()
    assert "create_mission" in reg.names()
    assert "dispatch_mission" in reg.names()
    assert "abort_mission" in reg.names()
    assert reg._tools["create_mission"].permission == "sensitive"
    assert reg._tools["list_drones"].permission == "readonly"
