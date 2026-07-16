"""Unit tests for Copilot v0.1 (schemas, tool registry, agent)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.schemas.copilot import ApprovalDecision, MessageRequest
from app.services.copilot_agent import VALID_INTENTS, CopilotAgent
from app.services.tool_registry import (
    ToolContext,
    ToolRegistry,
    build_default_registry,
)


@pytest.mark.asyncio
async def test_tool_registry_list_drones():
    """The default registry has list_drones; with db=None it returns []."""
    reg = build_default_registry()
    ctx = ToolContext(db=None)
    result = await reg.call("list_drones", {}, ctx)
    assert isinstance(result, dict)
    assert result == {"drones": []}


def test_message_request_valid():
    m = MessageRequest(prompt="巡检")
    assert m.prompt == "巡检"


def test_approval_decision_enum():
    d = ApprovalDecision(decision="approved")
    assert d.decision == "approved"


@pytest.mark.asyncio
async def test_copilot_agent_classify_intent_mocked():
    """classify_intent parses the LLM response and returns a valid label."""
    mock_llm = AsyncMock()
    # Anthropic-style content shape — see CopilotAgent._extract_text
    mock_llm.chat_completion = AsyncMock(
        return_value={"content": [{"type": "text", "text": "plan_mission"}]}
    )
    reg = ToolRegistry()
    agent = CopilotAgent(mock_llm, reg)
    intent = await agent.classify_intent("规划一个巡检任务")
    assert intent in VALID_INTENTS
    assert intent == "plan_mission"
