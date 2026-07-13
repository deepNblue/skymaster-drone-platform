"""Copilot Agent v2.0 (T4.0) — Function Calling tool loop.

Upgrade from v0.1 (intent classification only) to a full agentic loop:

    while step < MAX_STEPS:
        response = llm(messages, tools=registry.get_specs())
        if response.tool_use:
            result = await registry.call(tool_name, tool_args, ctx)
            messages.append(assistant tool_use)
            messages.append(user tool_result)
            continue
        else:
            return response.text

Key design decisions
--------------------

1. **Provider abstraction** · Both Anthropic-style and OpenAI-style
   Function Calling response shapes are parsed to a unified
   ``ToolCall`` dataclass. This lets us swap providers (Volcengine Ark
   vs direct Anthropic) without touching the loop.

2. **Sensitive tool gate** · Tools with ``permission="sensitive"`` are
   NOT auto-invoked. Instead the loop writes a ``CopilotApproval`` row
   and emits an ``approval_required`` event to the SSE stream. The
   user's approval endpoint resumes the loop with the tool result.

3. **Step budget + timeout** · Hard cap on total tool calls (default 8)
   to prevent runaway loops. Per-turn wall clock cap (30s default).

4. **Deterministic trace** · Every step (llm_call / tool_call /
   approval_required) is persisted as a ``CopilotTraceStep`` row so we
   can replay/debug conversations from Postgres alone.

5. **Fail soft** · If a tool call raises, we surface the error to the
   LLM as a ``tool_error`` result rather than aborting — the LLM often
   knows how to recover with a rephrased call.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_client import LLMClient
from app.services.tool_registry import ToolContext, ToolRegistry


MAX_TOOL_STEPS_DEFAULT = 8
PER_TURN_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Provider-agnostic response shapes
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """One tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMTurn:
    """Normalized single LLM response."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end"     # "end" | "tool_use" | "error"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def _parse_llm_response(resp: dict[str, Any]) -> LLMTurn:
    """Parse either Anthropic or OpenAI Function Calling response.

    Anthropic shape:
        {"stop_reason":"tool_use", "content":[
           {"type":"text","text":"..."},
           {"type":"tool_use","id":"toolu_...", "name":"...", "input":{...}}]}

    OpenAI shape:
        {"choices":[{"finish_reason":"tool_calls", "message":{
           "content":"...", "tool_calls":[
             {"id":"call_...", "type":"function",
              "function":{"name":"...", "arguments":"json str"}}]}}]}
    """
    turn = LLMTurn()

    # Anthropic
    content = resp.get("content")
    stop = resp.get("stop_reason")
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                text_parts.append(str(part.get("text") or ""))
            elif ptype == "tool_use":
                turn.tool_calls.append(ToolCall(
                    id=str(part.get("id") or ""),
                    name=str(part.get("name") or ""),
                    arguments=part.get("input") or {},
                ))
        turn.text = "\n".join(t for t in text_parts if t).strip()
        turn.stop_reason = "tool_use" if turn.tool_calls else (stop or "end")
        return turn

    # OpenAI
    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        msg = first.get("message") or {}
        if isinstance(msg, dict):
            turn.text = str(msg.get("content") or "").strip()
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                turn.tool_calls.append(ToolCall(
                    id=str(tc.get("id") or ""),
                    name=str(fn.get("name") or ""),
                    arguments=args,
                ))
        turn.stop_reason = (
            "tool_use" if turn.tool_calls else str(first.get("finish_reason") or "end")
        )
        return turn

    turn.stop_reason = "error"
    return turn


# ---------------------------------------------------------------------------
# Message assembly — build the "next" turn's messages
# ---------------------------------------------------------------------------


def _messages_add_tool_use(
    messages: list[dict[str, Any]], calls: list[ToolCall], provider: str,
) -> None:
    """Append an assistant turn that requested tool calls."""
    if provider == "anthropic":
        content = [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
            for c in calls
        ]
        messages.append({"role": "assistant", "content": content})
    else:  # openai
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": c.id, "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in calls
            ],
        })


def _messages_add_tool_result(
    messages: list[dict[str, Any]], call_id: str, name: str,
    result: Any, provider: str, is_error: bool = False,
) -> None:
    """Append the tool's result message."""
    payload = json.dumps(result, ensure_ascii=False, default=str)
    if provider == "anthropic":
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": payload,
                "is_error": is_error,
            }],
        })
    else:  # openai
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": payload,
        })


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    max_tool_steps: int = MAX_TOOL_STEPS_DEFAULT
    per_turn_timeout: float = PER_TURN_TIMEOUT_SECONDS
    system_prompt: str = (
        "你是无人机管控平台的智能副驾（Copilot）。"
        "你能帮用户完成飞行任务规划、无人机状态查询、空域检查、气象查询等工作。\n"
        "使用工具时请确保参数完整、准确；对涉及资产变更（创建任务、派单等）的操作，"
        "会自动触发审批流程，你只需说明意图并调用相应工具即可。\n"
        "若用户请求超出你的工具能力，请直接以中文回答，不要臆造工具。"
    )


class Emitter:
    """Wrap the SSE emit callback into a stateful helper."""
    def __init__(self, cb: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self.cb = cb

    async def status(self, stage: str, **kv: Any) -> None:
        await self.cb({"type": "status", "data": {"stage": stage, **kv}})

    async def token(self, text: str) -> None:
        await self.cb({"type": "text", "data": {"text": text}})

    async def tool(self, event: str, name: str, **kv: Any) -> None:
        await self.cb({"type": "tool", "data": {"event": event, "name": name, **kv}})

    async def approval(self, tool: str, args: dict[str, Any], approval_id: str) -> None:
        await self.cb({"type": "approval_required", "data": {
            "tool": tool, "arguments": args, "approval_id": approval_id,
        }})

    async def error(self, stage: str, error: str) -> None:
        await self.cb({"type": "error", "data": {"stage": stage, "error": error}})

    async def done(self, **kv: Any) -> None:
        await self.cb({"type": "done", "data": kv})


class CopilotAgentV2:
    """Full-loop Function Calling agent."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        config: AgentConfig | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.config = config or AgentConfig()
        self.provider = "anthropic" if llm.protocol == "anthropic" else "openai"

    async def _call_tool(
        self, call: ToolCall, ctx: ToolContext,
    ) -> tuple[Any, bool]:
        """Invoke a registered tool. Returns (result, is_error)."""
        try:
            result = await self.registry.call(call.name, call.arguments, ctx)
            return result, False
        except KeyError as exc:
            return {"error": f"unknown tool {call.name!r}: {exc}"}, True
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "type": exc.__class__.__name__}, True

    async def _persist_step(
        self, db: Optional[AsyncSession], trace_id: Optional[UUID],
        kind: str, payload: dict[str, Any],
    ) -> None:
        """Best-effort persist a trace step. Never fails the loop.

        Maps our internal (kind, payload) into the fixed
        ``copilot_trace_steps`` schema (idx, tool, args, result, error).
        """
        if db is None or trace_id is None:
            return
        try:
            from app.models.copilot_trace_step import CopilotTraceStep
            # Derive schema fields from our internal payload
            idx = int(payload.get("step") or 0)
            tool = payload.get("tool") or kind
            args = payload.get("arguments") or None
            result = payload.get("result") or {"payload": payload}
            duration_ms = payload.get("latency_ms")
            error = None
            if payload.get("is_error"):
                error = str(payload.get("result"))
            step = CopilotTraceStep(
                trace_id=trace_id, idx=idx, tool=str(tool)[:60],
                args=args if isinstance(args, dict) else None,
                result=result if isinstance(result, dict) else {"raw": str(result)},
                duration_ms=duration_ms,
                error=error,
            )
            db.add(step)
            await db.flush()
        except Exception:
            pass

    async def run(
        self,
        prompt: str,
        history: list[dict[str, Any]] | None,
        ctx: ToolContext,
        emit_cb: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        session_id: UUID,
        trace_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """Execute the full tool-calling loop.

        Returns a summary dict with ``text`` (final assistant answer),
        ``tool_calls`` (list of names invoked), ``pending_approvals``
        (list of approval IDs), ``stopped_reason``.
        """
        emit = Emitter(emit_cb)
        specs = self.registry.get_specs()

        messages: list[dict[str, Any]] = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        summary: dict[str, Any] = {
            "text": "",
            "tool_calls": [],
            "pending_approvals": [],
            "stopped_reason": "end",
            "steps": 0,
        }

        started = time.monotonic()

        for step in range(self.config.max_tool_steps + 1):
            summary["steps"] = step + 1
            elapsed = time.monotonic() - started
            if elapsed > self.config.per_turn_timeout:
                summary["stopped_reason"] = "timeout"
                await emit.error("timeout", f"per-turn timeout {self.config.per_turn_timeout:.0f}s exceeded")
                break

            await emit.status("llm_call", step=step + 1)
            t0 = time.monotonic()
            try:
                # LLM providers can misbehave; give them a per-call timeout too
                remaining = max(1.0, self.config.per_turn_timeout - elapsed)
                resp = await asyncio.wait_for(
                    self.llm.chat_completion(
                        messages=[{"role": "system", "content": self.config.system_prompt}]
                                 + messages,
                        tools=specs,
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                summary["stopped_reason"] = "timeout"
                await emit.error("llm_call", "timeout")
                break
            except Exception as exc:  # noqa: BLE001
                summary["stopped_reason"] = "llm_error"
                await emit.error("llm_call", str(exc))
                break

            turn = _parse_llm_response(resp)
            latency_ms = int((time.monotonic() - t0) * 1000)
            await self._persist_step(db, trace_id, "llm_call", {
                "step": step + 1, "latency_ms": latency_ms,
                "text_length": len(turn.text or ""),
                "tool_calls": [tc.name for tc in turn.tool_calls],
                "stop_reason": turn.stop_reason,
            })

            if not turn.wants_tools:
                # Final answer
                summary["text"] = turn.text
                if turn.text:
                    await emit.token(turn.text)
                summary["stopped_reason"] = "end"
                break

            # LLM asked for tools — check step budget BEFORE executing
            if step + len(turn.tool_calls) > self.config.max_tool_steps:
                summary["stopped_reason"] = "step_budget"
                await emit.error("tool_call", "step budget exhausted")
                break

            _messages_add_tool_use(messages, turn.tool_calls, self.provider)

            # Execute (or defer) each tool call
            all_sensitive_pending = False
            for call in turn.tool_calls:
                spec = self.registry._tools.get(call.name)
                if spec is None:
                    await emit.tool("error", call.name, error="unknown tool")
                    _messages_add_tool_result(
                        messages, call.id, call.name,
                        {"error": "unknown tool"}, self.provider, is_error=True,
                    )
                    continue

                # Sensitive tools go through approval
                if spec.permission == "sensitive":
                    approval_id = await self._enqueue_approval(
                        db, session_id, trace_id, call,
                    )
                    summary["pending_approvals"].append(approval_id)
                    await emit.approval(call.name, call.arguments, approval_id)
                    await self._persist_step(db, trace_id, "approval_required", {
                        "tool": call.name, "approval_id": approval_id,
                        "arguments": call.arguments,
                    })
                    # Simulate a synthetic tool_result so the LLM knows it's pending
                    _messages_add_tool_result(
                        messages, call.id, call.name,
                        {"status": "pending_approval", "approval_id": approval_id},
                        self.provider,
                    )
                    all_sensitive_pending = True
                    continue

                # Read-only tool — execute immediately
                await emit.tool("start", call.name, arguments=call.arguments)
                result, is_error = await self._call_tool(call, ctx)
                await emit.tool(
                    "end" if not is_error else "error",
                    call.name, result=result,
                )
                summary["tool_calls"].append(call.name)
                await self._persist_step(db, trace_id, "tool_call", {
                    "tool": call.name, "arguments": call.arguments,
                    "result": result, "is_error": is_error,
                })
                _messages_add_tool_result(
                    messages, call.id, call.name,
                    result, self.provider, is_error=is_error,
                )

            if all_sensitive_pending and not any(
                self.registry._tools.get(c.name, None)
                and self.registry._tools[c.name].permission != "sensitive"
                for c in turn.tool_calls
            ):
                # Every tool was sensitive → yield control back to user; the
                # approval endpoint will resume the loop after decision.
                summary["stopped_reason"] = "approval_required"
                break

        else:
            summary["stopped_reason"] = "step_budget"
            await emit.error("agent", "max_tool_steps exceeded")

        await emit.done(
            stopped_reason=summary["stopped_reason"],
            tool_calls=summary["tool_calls"],
            pending_approvals=summary["pending_approvals"],
        )
        return summary

    async def _enqueue_approval(
        self, db: Optional[AsyncSession],
        session_id: UUID, trace_id: Optional[UUID],
        call: ToolCall,
    ) -> str:
        """Create a CopilotApproval row and return its ID as a string.

        The existing CopilotApproval schema is minimal — we stash the
        tool_name + arguments in ``required_reason`` as a compact JSON
        blob so approver UIs can render them without a schema migration.
        """
        if db is None or trace_id is None:
            return f"pending-{call.id}"
        try:
            from app.models.copilot_approval import CopilotApproval
            required_reason = json.dumps({
                "tool": call.name,
                "arguments": call.arguments,
                "session_id": str(session_id),
            }, ensure_ascii=False)
            approval = CopilotApproval(
                trace_id=trace_id,
                required_reason=required_reason,
            )
            db.add(approval)
            await db.flush()
            return str(approval.id)
        except Exception:
            return f"pending-{call.id}"


__all__ = [
    "AgentConfig",
    "CopilotAgentV2",
    "LLMTurn",
    "ToolCall",
    "_parse_llm_response",   # exported for tests
]
