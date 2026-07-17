"""E2.3 · Agent 与长期记忆集成的最小冒烟."""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services import copilot_memory as mem_svc
from app.services.auth import hash_password
from app.services.copilot_agent_v2 import AgentConfig, CopilotAgentV2
from app.services.tool_registry import ToolContext, build_default_registry

pytestmark = pytest.mark.asyncio


class _FakeLLM:
    """LLM stub that returns a minimal anthropic-shaped response."""

    protocol = "anthropic"

    def __init__(self) -> None:
        self.last_messages: list[dict[str, Any]] = []

    async def chat_completion(
        self, messages: list[dict[str, Any]],
        tools: list[Any] | None = None, model: str | None = None,
    ) -> dict[str, Any]:
        self.last_messages = messages
        # Anthropic-shape reply with a single text block, no tool_use
        return {
            "content": [{"type": "text", "text": "[stub-reply]"}],
            "stop_reason": "end_turn",
        }


async def _mkuser() -> tuple[UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid,
            email=f"agmem+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return uid, org


async def _run_agent(
    agent: CopilotAgentV2, org: UUID, uid: UUID, prompt: str,
) -> None:
    S = async_sessionmaker(engine, expire_on_commit=False)

    async def emit(_e: dict[str, Any]) -> None: ...

    async with S() as s:
        await agent.run(
            prompt=prompt,
            history=[],
            ctx=ToolContext(org_id=org, user_id=uid),
            emit_cb=emit,
            session_id=uuid4(),
            db=s,
        )


async def test_agent_injects_memory_into_system_prompt(client) -> None:
    uid, org = await _mkuser()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await mem_svc.create_memory(
            s, org_id=org, user_id=uid,
            kind="preference",
            content="巡检默认时长 40 分钟",
            tags=["巡检"], weight=80,
        )

    fake = _FakeLLM()
    agent = CopilotAgentV2(
        llm=fake,  # type: ignore[arg-type]
        registry=build_default_registry(),
        config=AgentConfig(
            system_prompt="你是无人机助手", max_tool_steps=0,
        ),
    )
    await _run_agent(agent, org, uid, "帮我安排巡检任务")

    sys_msg = next(m for m in fake.last_messages if m.get("role") == "system")
    assert "长期记忆" in sys_msg["content"]
    assert "巡检默认时长 40 分钟" in sys_msg["content"]


async def test_agent_no_memory_when_none_stored(client) -> None:
    uid, org = await _mkuser()
    fake = _FakeLLM()
    agent = CopilotAgentV2(
        llm=fake,  # type: ignore[arg-type]
        registry=build_default_registry(),
        config=AgentConfig(system_prompt="baseline", max_tool_steps=0),
    )
    await _run_agent(agent, org, uid, "hi")
    sys_msg = next(m for m in fake.last_messages if m.get("role") == "system")
    assert "长期记忆" not in sys_msg["content"]
    assert sys_msg["content"].strip() == "baseline"
