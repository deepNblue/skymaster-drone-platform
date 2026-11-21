"""Copilot LLM Fallback — R21 Step C.

When the deterministic rule-based intent parser (``copilot_intent``) returns
a confidence below ``settings.copilot_llm_fallback_threshold``, this module
lets us **optionally** consult an LLM to disambiguate.

Design goals
------------

1. **Off by default.** The platform must run without any LLM call — this
   fallback is purely opt-in via ``COPILOT_LLM_FALLBACK=true``.
2. **Deterministic surface.** We do not let the LLM invent new intents;
   its output is coerced to the same 6-label vocabulary the rule parser
   already emits. Anything unrecognised → ``unknown`` (identical to a
   confident rule-parser miss).
3. **Never crash.** Any LLM error → fall through to the original parse
   with an added ``llm_error`` note.
4. **Same shape.** ``fallback_parse`` returns a ``ParsedIntent`` — the
   rest of the Copilot pipeline is unaware of the fallback.

The fallback re-uses ``LLMClient`` already configured by the v0.1 Copilot,
so no new API-key surface is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.services.copilot_intent import (
    ParsedIntent,
    parse_intent as _rule_parse,
)

log = logging.getLogger(__name__)


# The exact intent vocabulary the rest of the stack understands.
_VALID_INTENTS = (
    "takeoff", "land", "return_home", "hover", "goto_waypoint",
    "start_recording", "stop_recording", "vision_query",
    "generate_report", "help", "status", "unknown",
)


_SYSTEM_PROMPT = (
    "你是无人机管控平台的意图分类器。"
    "根据用户中文/英文输入，从下列意图中挑选最合适的一个："
    + "、".join(_VALID_INTENTS)
    + "。返回严格 JSON：{\"intent\":\"...\",\"args\":{...}}。"
    "goto_waypoint 时 args 需含 lat/lng（可选 alt，米）。"
    "vision_query 时 args 需含 label。"
    "不确定时返回 {\"intent\":\"unknown\",\"args\":{}}。"
    "不要输出任何多余文字。"
)


def _extract_text(response: dict[str, Any]) -> str:
    """Handle both Anthropic and OpenAI response envelopes."""
    if not response:
        return ""
    content = response.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return str(part.get("text") or "").strip()
    if isinstance(content, str):
        return content.strip()
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            return str(msg.get("content") or "").strip()
    return ""


def _coerce_llm_output(raw: str) -> dict[str, Any] | None:
    """Best-effort JSON parse — tolerates leading/trailing prose or code fences.

    Returns None if no legal JSON with an ``intent`` key can be recovered.
    """
    if not raw:
        return None
    # Strip common code-fence wrappers.
    text = raw.strip()
    if text.startswith("```"):
        # remove ```json / ``` opening
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    # Try direct JSON.
    for candidate in (text, _first_json_object(text)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "intent" in obj:
                return obj
        except Exception:
            continue
    return None


def _first_json_object(text: str) -> str | None:
    """Extract the first balanced ``{...}`` substring."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


async def fallback_parse(
    text: str,
    *,
    llm_client: Any,
    model: str | None = None,
    timeout_s: float = 6.0,
) -> ParsedIntent:
    """Rule-parse first; if low confidence and fallback enabled, ask the LLM.

    Callers pass an already-configured ``LLMClient`` so this module has no
    knowledge of API endpoints / keys.
    """
    rule = _rule_parse(text)
    from app.config import settings

    if not settings.copilot_llm_fallback:
        return rule
    if rule.confidence >= settings.copilot_llm_fallback_threshold:
        return rule
    if llm_client is None:
        return rule

    try:
        response = await asyncio.wait_for(
            llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                model=model,
            ),
            timeout=timeout_s,
        )
    except Exception as exc:
        log.info("Copilot LLM fallback errored, keeping rule parse: %s", exc)
        rule.args = {**rule.args, "llm_error": str(exc)[:200]}
        return rule

    raw = _extract_text(response)
    parsed_obj = _coerce_llm_output(raw)
    if not parsed_obj:
        rule.args = {**rule.args, "llm_error": "unparseable"}
        return rule

    intent = str(parsed_obj.get("intent") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        rule.args = {**rule.args, "llm_intent_raw": intent[:32]}
        return rule
    if intent == "unknown":
        # LLM also can't classify → keep the rule outcome (which already
        # ships a helpful clarify prompt).
        return rule

    args = parsed_obj.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    # goto_waypoint requires numeric lat/lng — reject if malformed.
    if intent == "goto_waypoint":
        try:
            args = {
                "lat": float(args["lat"]),
                "lng": float(args["lng"]),
                **({"alt": float(args["alt"])} if "alt" in args else {}),
            }
        except Exception:
            rule.args = {**rule.args, "llm_intent_raw": "goto_waypoint(malformed args)"}
            return rule

    if intent == "vision_query":
        label = str(args.get("label") or "").strip()
        if not label:
            rule.args = {**rule.args, "llm_intent_raw": "vision_query(no label)"}
            return rule
        args = {"label": label}

    return ParsedIntent(
        intent=intent,
        args={**args, "via": "llm_fallback"},
        confidence=0.65,   # denote "LLM-derived, medium confidence"
        clarify=None,
    )
