"""Tests for R21 Step C — Copilot LLM fallback."""
from __future__ import annotations

import pytest


class _FakeLLM:
    """Minimal stub matching LLMClient.chat_completion shape."""

    def __init__(self, response=None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    async def chat_completion(self, messages, model=None, tools=None):
        self.calls.append({"messages": messages, "model": model})
        if self.raises:
            raise self.raises
        return self.response


def _anthropic(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _openai(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


# ---------------------------------------------------------------------------
# Off-by-default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_disabled_returns_rule_only(monkeypatch):
    """When settings.copilot_llm_fallback = False, the LLM must not be called
    even for unknown inputs."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", False)
    llm = _FakeLLM(response=_anthropic('{"intent":"takeoff","args":{}}'))
    result = await fallback_parse("完全乱码 xyz 123", llm_client=llm)
    assert result.intent == "unknown"
    assert llm.calls == []   # LLM was NOT called


@pytest.mark.asyncio
async def test_fallback_enabled_but_rule_confident(monkeypatch):
    """When the rule parser is already confident, LLM stays untouched."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    monkeypatch.setattr(settings, "copilot_llm_fallback_threshold", 0.6)
    llm = _FakeLLM(response=_anthropic('{"intent":"land","args":{}}'))
    result = await fallback_parse("起飞", llm_client=llm)
    assert result.intent == "takeoff"
    assert result.confidence == 1.0
    assert llm.calls == []


# ---------------------------------------------------------------------------
# Fallback invoked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_invoked_on_unknown(monkeypatch):
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    monkeypatch.setattr(settings, "copilot_llm_fallback_threshold", 0.6)
    llm = _FakeLLM(response=_anthropic('{"intent":"return_home","args":{}}'))
    result = await fallback_parse("咕咕 mystery xyz", llm_client=llm)
    assert result.intent == "return_home"
    assert result.args.get("via") == "llm_fallback"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_fallback_handles_code_fenced_output(monkeypatch):
    """LLMs love to wrap JSON in ```json fences. We must strip them."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(response=_anthropic('```json\n{"intent":"hover","args":{}}\n```'))
    result = await fallback_parse("先停这别动", llm_client=llm)
    assert result.intent == "hover"


@pytest.mark.asyncio
async def test_fallback_handles_prose_wrapped_json(monkeypatch):
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    text = 'Sure, here you go: {"intent":"start_recording","args":{}} — that should do it.'
    llm = _FakeLLM(response=_openai(text))
    result = await fallback_parse("给我录一下", llm_client=llm)
    assert result.intent == "start_recording"


@pytest.mark.asyncio
async def test_fallback_goto_waypoint_coerces_args(monkeypatch):
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(response=_anthropic(
        '{"intent":"goto_waypoint","args":{"lat":"30.5","lng":"104.06","alt":"120"}}',
    ))
    result = await fallback_parse("过去看看那边", llm_client=llm)
    assert result.intent == "goto_waypoint"
    assert result.args["lat"] == 30.5
    assert result.args["lng"] == 104.06
    assert result.args["alt"] == 120


@pytest.mark.asyncio
async def test_fallback_goto_malformed_args_rejected(monkeypatch):
    """If LLM returns goto_waypoint without lat/lng, treat as failure and
    keep the rule outcome — never send an execution with bad coords."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(response=_anthropic('{"intent":"goto_waypoint","args":{"place":"厂区"}}'))
    result = await fallback_parse("去厂区看看", llm_client=llm)
    assert result.intent == "unknown"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_llm_error_falls_through(monkeypatch):
    """LLM error must not raise — we log and keep the rule parse."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(raises=RuntimeError("upstream 503"))
    result = await fallback_parse("神秘咒语", llm_client=llm)
    assert result.intent == "unknown"
    assert "llm_error" in result.args


@pytest.mark.asyncio
async def test_fallback_bogus_intent_rejected(monkeypatch):
    """LLM returns something outside the vocabulary → we don't propagate it."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(response=_anthropic('{"intent":"self_destruct","args":{}}'))
    result = await fallback_parse("按红色按钮", llm_client=llm)
    assert result.intent == "unknown"
    assert result.args.get("llm_intent_raw", "").startswith("self_destruct")


@pytest.mark.asyncio
async def test_fallback_unparseable_output(monkeypatch):
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    llm = _FakeLLM(response=_anthropic("just prose, no JSON at all"))
    result = await fallback_parse("咕咕", llm_client=llm)
    assert result.intent == "unknown"
    assert result.args.get("llm_error") == "unparseable"


@pytest.mark.asyncio
async def test_fallback_no_llm_client(monkeypatch):
    """Even with fallback enabled, missing client must not crash."""
    from app.services.copilot_llm_fallback import fallback_parse
    from app.config import settings

    monkeypatch.setattr(settings, "copilot_llm_fallback", True)
    result = await fallback_parse("嗯嗯", llm_client=None)
    assert result.intent == "unknown"
