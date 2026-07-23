"""E2.4b · LLM-driven Task Chain planner and reflector.

给定一个自然语言目标，让 LLM 产出 Task Chain 的初始 `plan` (list of subtasks)。
运行时若一步失败或产出与预期偏差，反射器可以让 LLM 提出一个
`replace_remaining` / `append_step` 的 revision，并把 reason 显式写入
`CopilotTaskChainRevision`。

设计原则：
- Planner 只负责产出 JSON，不直接落库；由上层 API 决定是否创建 chain
- LLM 只能选择 registry 白名单里的工具；违反时 planner 报错让上层重试或降级
- 输出 schema 固定：`{"subtasks": [{title, tool, args, why}, ...]}`
- 反射器输入是当前 chain + steps + 失败 step 的错误
- 若 LLM 未返回合法 JSON，抛 `PlannerError`，由上层选择降级到"手写 plan"或
  直接把 goal 转成一个 talk-only subtask
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.copilot_task_chain import Subtask
from app.services.llm_client import LLMClient
from app.services.tool_registry import ToolRegistry


class PlannerError(RuntimeError):
    pass


PLANNER_SYS_PROMPT = """你是 SkyMaster 无人机管控平台的 Task Chain 规划器。
用户会给出一个自然语言目标，你需要产出一份分步执行计划（subtask list），
每一步指定一个工具调用与参数。

严格遵守：
1. 只能使用「可用工具」列表里的工具名，禁止发明工具。
2. 最多 8 个步骤；步骤越少越好，能一步的绝不拆成两步。
3. 每个 subtask 必须包含 title (中文≤30字)、tool、args (JSON 对象)、why (≤80字 解释为什么这一步)。
4. args 里的字段类型必须匹配工具 schema；未知字段留空 `{}`。
5. 输出必须是**纯 JSON**，形如：
   {"subtasks": [{"title": "...", "tool": "...", "args": {...}, "why": "..."}]}
   不要输出 markdown 代码块、不要输出任何解释文字。
6. 如果目标无法通过现有工具完成，输出：
   {"error": "..."}   // 简要说明缺哪个能力
"""


REFLECTOR_SYS_PROMPT = """你是 SkyMaster Task Chain 反射器。
一个执行计划刚刚出错（或需要补充），你需要提出一个 revision。

严格遵守：
1. 只能返回 kind ∈ {append_step, replace_remaining, mark_completed, abort}。
2. append_step / replace_remaining 必须给出 `new_tail`（subtask list，最多 6 条）。
3. mark_completed / abort 无需 new_tail。
4. 必须给出 reason（中文≤120字，说明为什么这样调整）。
5. 输出纯 JSON：
   {"kind": "...", "new_tail": [...], "reason": "..."}
   不要输出 markdown 代码块或额外解释。
"""


@dataclass
class PlanResult:
    subtasks: list[dict[str, Any]]  # 每条 = {"title", "tool", "args", "why"}
    raw_response: str


@dataclass
class RevisionSuggestion:
    kind: str
    new_tail: list[dict[str, Any]] | None
    reason: str
    raw_response: str


def _extract_text(response: dict[str, Any]) -> str:
    """Anthropic 与 OpenAI 兼容 payload 里的文本抽取."""
    # Anthropic
    content = response.get("content")
    if isinstance(content, list):
        parts = [
            blk.get("text", "") for blk in content
            if isinstance(blk, dict) and blk.get("type") == "text"
        ]
        if parts:
            return "".join(parts)
    # OpenAI
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):  # some providers wrap in blocks
            texts = [b.get("text", "") for b in c if isinstance(b, dict)]
            return "".join(texts)
    return ""


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # 去掉可能的 markdown fence
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 兜底: 匹配第一个花括号包裹的整体
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise PlannerError(f"invalid JSON response: {e}: {text[:200]!r}")
    raise PlannerError(f"no JSON object found in response: {text[:200]!r}")


def _tool_catalog(registry: ToolRegistry) -> str:
    """Compact human-readable tool catalog for the system prompt."""
    lines: list[str] = []
    for name in sorted(registry.names()):
        spec = registry.get(name)
        if spec is None:
            continue
        desc = (spec.description or "").strip().split("\n", 1)[0]
        # emit args schema property names only, to keep prompt short
        try:
            schema = spec.args_schema.model_json_schema()
            props = list((schema.get("properties") or {}).keys())
            required = schema.get("required") or []
            arg_hint = ", ".join(
                f"{p}{'*' if p in required else ''}" for p in props
            ) or "-"
        except Exception:  # noqa: BLE001
            arg_hint = "-"
        lines.append(f"- {name}({arg_hint}): {desc[:80]}")
    return "\n".join(lines)


async def plan(
    *,
    goal: str,
    llm: LLMClient,
    registry: ToolRegistry,
    model: str | None = None,
) -> PlanResult:
    """LLM-driven planning. Raises PlannerError on unparseable output."""
    catalog = _tool_catalog(registry)
    sys = PLANNER_SYS_PROMPT + "\n\n可用工具:\n" + catalog
    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": f"目标: {goal}"},
    ]
    resp = await llm.chat_completion(messages=messages, model=model)
    raw = _extract_text(resp)
    data = _parse_json(raw)
    if "error" in data:
        raise PlannerError(f"planner refused: {data['error']}")
    subtasks = data.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise PlannerError(f"planner returned no subtasks: {raw[:200]!r}")
    if len(subtasks) > 8:
        raise PlannerError(f"plan too long ({len(subtasks)}), max 8")
    # 逐条校验并归一化（会额外触发 Subtask.from_dict 的字段校验）
    normalized: list[dict[str, Any]] = []
    known = set(registry.names())
    for i, s in enumerate(subtasks):
        st = Subtask.from_dict(s)
        if st.tool not in known:
            raise PlannerError(f"subtask[{i}] uses unknown tool: {st.tool}")
        normalized.append(st.to_dict())
    return PlanResult(subtasks=normalized, raw_response=raw)


async def reflect(
    *,
    goal: str,
    plan_json: list[dict[str, Any]],
    steps_summary: list[dict[str, Any]],
    trigger: str,
    llm: LLMClient,
    registry: ToolRegistry,
    model: str | None = None,
) -> RevisionSuggestion:
    """Ask LLM how to revise the tail of the plan after an execution event.

    Parameters
    ----------
    goal:
        The chain's original goal.
    plan_json:
        Current full plan.
    steps_summary:
        Compact history of steps run so far — each item is
        `{step_index, tool, status, output_short, error}`.
    trigger:
        "step_failed" | "user_reflect" | "off_track"
    """
    catalog = _tool_catalog(registry)
    sys = REFLECTOR_SYS_PROMPT + "\n\n可用工具:\n" + catalog
    user_payload = {
        "goal": goal,
        "plan": plan_json,
        "history": steps_summary,
        "trigger": trigger,
    }
    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    resp = await llm.chat_completion(messages=messages, model=model)
    raw = _extract_text(resp)
    data = _parse_json(raw)
    kind = data.get("kind")
    if kind not in ("append_step", "replace_remaining", "mark_completed", "abort"):
        raise PlannerError(f"reflector returned invalid kind: {kind}")
    new_tail = data.get("new_tail")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise PlannerError("reflector missing reason")
    if kind in ("append_step", "replace_remaining"):
        if not isinstance(new_tail, list):
            raise PlannerError(f"{kind} requires new_tail list")
        if len(new_tail) > 6:
            raise PlannerError(f"new_tail too long ({len(new_tail)}), max 6")
        normalized: list[dict[str, Any]] = []
        known = set(registry.names())
        for i, s in enumerate(new_tail):
            st = Subtask.from_dict(s)
            if st.tool not in known:
                raise PlannerError(f"new_tail[{i}] uses unknown tool: {st.tool}")
            normalized.append(st.to_dict())
        new_tail = normalized
    else:
        new_tail = None
    return RevisionSuggestion(
        kind=kind, new_tail=new_tail, reason=reason, raw_response=raw,
    )


def summarize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Convert CopilotTaskChainStep rows into short LLM-facing dicts."""
    out: list[dict[str, Any]] = []
    for s in steps:
        raw_out = s.output_json
        # Truncate long outputs to avoid blowing up context
        try:
            short = json.dumps(raw_out, ensure_ascii=False)[:400] if raw_out is not None else None
        except Exception:  # noqa: BLE001
            short = "<unserializable>"
        out.append({
            "step_index": s.step_index,
            "tool": s.tool,
            "status": s.status,
            "output_short": short,
            "error": s.error,
        })
    return out
