"""Copilot Agent v0.1 — LLM-driven intent + tool execution.

Restored module — provides the original interface required by
``app/api/v1/copilot.py`` and ``tests/test_copilot.py``. The new
rule-based intent parser used by v2.0 R20 Track B lives in
``copilot_intent.py`` to avoid stepping on this file.

Interface (as consumed by callers)
==================================

- ``VALID_INTENTS``            — tuple of legal intent labels
- ``class CopilotAgent(llm, registry)``
    - ``async classify_intent(prompt: str) -> str``
    - ``async run(prompt, ctx, emit, session_id, db)`` — streams events
      via ``emit(dict)``; persists CopilotTrace rows to ``db``.
    - ``_extract_text(response)``  — Anthropic + OpenAI content shape.
"""
from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_client import LLMClient
from app.services.tool_registry import ToolContext, ToolRegistry


VALID_INTENTS: tuple[str, ...] = (
    "plan_mission",
    "control_drone",
    "query_data",
    "chat",
    "clarify",
    "unknown",
)


_INTENT_SYSTEM_PROMPT = (
    "你是无人机管控平台的意图分类器。请从以下 6 个意图中选择最匹配的一个："
    + "、".join(VALID_INTENTS)
    + "。仅返回意图关键字，不要解释。"
)


class CopilotAgent:
    """Minimal LLM-driven agent — classify intent, then optionally invoke a tool.

    The implementation focuses on the *shape* required by tests and the
    HTTP router: streaming ``emit`` callback and persisted traces. The real
    tool-selection logic lives in ``ToolRegistry``; the agent only decides
    the intent label and delegates from there.
    """

    def __init__(self, llm: LLMClient, registry: ToolRegistry) -> None:
        self.llm = llm
        self.registry = registry

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        """Handle both Anthropic (content=[{type:text,text:..}]) and OpenAI
        (choices=[{message:{content:..}}]) shapes."""
        if not response:
            return ""
        # Anthropic-style
        content = response.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text") or "").strip()
        if isinstance(content, str):
            return content.strip()
        # OpenAI-style
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                return str(msg.get("content") or "").strip()
        return ""

    async def classify_intent(self, prompt: str) -> str:
        response = await self.llm.chat_completion(
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = self._extract_text(response).lower().strip()
        # Return the first VALID_INTENTS token found in the reply; default to
        # "unknown" so downstream code always has a legal label.
        for intent in VALID_INTENTS:
            if intent in raw:
                return intent
        return "unknown"

    # ------------------------------------------------------------------
    # Streaming run
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        ctx: ToolContext,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        session_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Classify intent, stream progress, and record a CopilotTrace.

        Intentionally conservative: we do NOT auto-invoke sensitive tools.
        The router streams status events; sensitive operations flow through
        the approval endpoint.
        """
        # Emit start
        await emit({"type": "status", "data": {"stage": "classify", "prompt": prompt}})

        t0 = time.monotonic()
        try:
            intent = await self.classify_intent(prompt)
        except Exception as exc:  # pragma: no cover
            await emit({"type": "error", "data": {"stage": "classify", "error": str(exc)}})
            intent = "unknown"
        latency_ms = int((time.monotonic() - t0) * 1000)

        await emit({"type": "intent", "data": {"intent": intent, "latency_ms": latency_ms}})

        # Persist a lightweight trace row so ``list_traces`` can render it.
        try:
            from app.models.copilot_session import CopilotTrace  # local import

            trace = CopilotTrace(
                session_id=session_id,
                org_id=ctx.org_id,
                intent=intent,
                prompt=prompt,
                latency_ms=latency_ms,
                payload={"intent": intent},
            )
            db.add(trace)
            await db.commit()
        except Exception:
            # Trace persistence is best-effort; agent must not fail because of it.
            pass

        await emit({"type": "done", "data": {"intent": intent}})
