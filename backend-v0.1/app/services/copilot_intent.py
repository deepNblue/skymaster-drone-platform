"""Copilot Agent — natural-language operator assistant.

The Copilot maps free-text into a small, well-defined set of *intents* and
*arguments* that the platform already knows how to execute (drone commands,
vision queries, report generation). It is deliberately **rules-first, LLM-
optional**:

  * A deterministic Chinese/English keyword+regex router covers the common
    operator utterances with sub-millisecond latency and zero cost.
  * An LLM fallback is invoked only when confidence is low, gated by
    ``settings.copilot_llm_enabled`` (default off).

This split keeps the hot control path predictable — an operator saying
"起飞" or "returning home" gets deterministic behavior; only ambiguous
phrases pay the LLM cost.

**Intents** (extensible):

    takeoff              → drone.command.takeoff
    land                 → drone.command.land
    return_home / rth    → drone.command.rth
    hover                → drone.command.hover
    goto_waypoint        → drone.command.goto {lat, lng, alt}
    start_recording      → mission.recording.start
    stop_recording       → mission.recording.stop
    vision_query         → vision.detections.recent {label?}
    generate_report      → report.generate {mission_id?}
    help / status        → agent.info

Every parsed turn returns::

    {
      intent, args, confidence, reply, tool_call, tool_result, clarify
    }
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedIntent:
    intent: str
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    clarify: str | None = None  # non-empty when the user should refine


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------


# Each rule: (intent, list-of-triggers, extractor)
# Triggers matched case-insensitively, both Chinese/English kept flat.
_RULES: list[tuple[str, list[str], Any]] = [
    ("takeoff",            ["起飞", "升空", "起飞吧", "takeoff", "take off", "launch"],       None),
    ("land",               ["降落", "着陆", "落地", "land now", "landing"],                  None),
    ("return_home",        ["返航", "回航", "回来", "return home", "rth", "come back"],       None),
    ("hover",              ["悬停", "定点", "hover", "hold position"],                        None),
    ("stop_recording",     ["停止录像", "停止拍摄", "stop recording"],                        None),
    ("start_recording",    ["开始录像", "开始拍摄", "start recording", "开始录制"],           None),
    ("generate_report",    ["生成报告", "任务报告", "报告一下", "generate report", "summary"], None),
    ("help",               ["帮助", "指令", "help", "commands", "你能做什么", "what can you do"], None),
    ("status",             ["状态", "怎么样", "status", "how is it going"],                    None),
]


# goto_waypoint accepts "去 <lat>,<lng>" / "goto lat,lng" / "飞到 x,y[,alt]"
_GOTO_RE = re.compile(
    r"(?:去|飞到|前往|goto|go to|fly to)\s*"
    r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s*[,，]\s*(-?\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)

# R21 G — altitude deltas ("再飞高 20m", "再降 10m", "climb by 15")
_ALT_DELTA_RE = re.compile(
    r"(?:再?)?"
    r"(?P<dir>飞高|升高|climb|climb by|go up|再爬升|降低|下降|再降|drop|descend|go down)\s*"
    r"(?P<n>\d+(?:\.\d+)?)\s*(?:m|米|米高|meter|meters)?",
    re.IGNORECASE,
)

# R21 G — "回到刚才的位置" / "回原点" — pure back-reference goto.
_BACK_REF_RE = re.compile(
    r"回到?\s*(?:刚才|之前|上次|previous|last)\s*(?:的?)?\s*(?:位置|地点|坐标|point|spot)",
    re.IGNORECASE,
)

# vision_query accepts "看到 <label> 了吗" / "any <label> detected" / "识别 <label>"
_VISION_RE = re.compile(
    r"(?:看到|检测到|识别到?|any\s+|detected|find|show me)\s*"
    r"([\w\u4e00-\u9fa5]+?)"
    r"(?:\s*了吗|\s*吗|\s*\?|\s*detected|$)",
    re.IGNORECASE,
)


def parse_intent(text: str) -> ParsedIntent:
    """Deterministic rule-based intent classifier.

    Returns a ParsedIntent with confidence in [0,1]:
      * 1.0 = exact keyword match
      * 0.8 = regex match with structured args
      * 0.0 = no match — the caller may then invoke the LLM fallback
    """
    if not text or not text.strip():
        return ParsedIntent("noop", confidence=0.0, clarify="请输入指令或问题")

    t = text.strip()
    tl = t.lower()

    # 1) Bare keyword rules — highest priority.
    for intent, triggers, _extractor in _RULES:
        for trig in triggers:
            if trig.lower() in tl:
                return ParsedIntent(intent, confidence=1.0)

    # 2) goto_waypoint with args.
    m = _GOTO_RE.search(t)
    if m:
        args: dict[str, Any] = {"lat": float(m.group(1)), "lng": float(m.group(2))}
        if m.group(3):
            args["alt"] = float(m.group(3))
        return ParsedIntent("goto_waypoint", args=args, confidence=0.9)

    # 2b) R21 G — pure back-reference goto ("回到刚才的位置").
    if _BACK_REF_RE.search(t):
        return ParsedIntent("goto_waypoint", args={}, confidence=0.6)

    # 2c) R21 G — altitude delta ("再飞高 20m", "climb 10").
    m = _ALT_DELTA_RE.search(t)
    if m:
        direction = m.group("dir").lower()
        n = float(m.group("n"))
        sign = -1.0 if any(k in direction for k in
                            ("降", "drop", "descend", "go down")) else 1.0
        return ParsedIntent(
            "goto_waypoint",
            args={"alt_delta": round(sign * n, 3)},
            confidence=0.65,
        )

    # 3) vision_query — extract label.
    m = _VISION_RE.search(t)
    if m:
        label = m.group(1).strip("的了吗?？.。 ")
        # Filter noisy captures.
        if 1 <= len(label) <= 24:
            return ParsedIntent("vision_query", args={"label": label}, confidence=0.75)

    # 4) Fallback: unknown intent — ask for clarification.
    return ParsedIntent(
        "unknown",
        confidence=0.0,
        clarify=("我没听懂 · 试试：起飞 / 降落 / 返航 / 悬停 / 去 <lat>,<lng> / "
                "看到 <label> 吗 / 生成报告 / 帮助"),
    )


# ---------------------------------------------------------------------------
# Reply templates — Chinese, concise.
# ---------------------------------------------------------------------------

_REPLIES = {
    "takeoff":         "✅ 已下发起飞指令 · 请注意周边空域",
    "land":            "✅ 已下发降落指令",
    "return_home":     "✅ 已启动一键返航",
    "hover":           "✅ 已切换悬停",
    "start_recording": "🎥 已开始录像",
    "stop_recording":  "🎥 已停止录像",
    "goto_waypoint":   "🧭 已发送前往航点 ({lat:.5f}, {lng:.5f}{alt_suffix})",
    "vision_query":    "🔍 已查询近 5 分钟 <{label}> 检测记录",
    "generate_report": "📝 已发起报告生成任务",
    "help":            ("你可以说：\n"
                        "· 起飞 / 降落 / 返航 / 悬停\n"
                        "· 去 30.5,104.05,120（前往航点）\n"
                        "· 看到 person 吗（视觉查询）\n"
                        "· 生成报告 / 状态"),
    "status":          "🟢 平台在线 · 通信正常",
    "noop":            "请输入指令或问题",
    "unknown":         "抱歉，我没理解你的指令",
}


def render_reply(parsed: ParsedIntent, tool_result: dict | None = None) -> str:
    """Format a natural-language reply for the given parsed intent."""
    if parsed.intent == "goto_waypoint":
        alt = parsed.args.get("alt")
        return _REPLIES["goto_waypoint"].format(
            lat=parsed.args["lat"], lng=parsed.args["lng"],
            alt_suffix=f", {alt:.0f}m" if alt is not None else "",
        )
    if parsed.intent == "vision_query":
        return _REPLIES["vision_query"].format(label=parsed.args.get("label", "*"))
    if parsed.intent == "unknown" and parsed.clarify:
        return parsed.clarify
    return _REPLIES.get(parsed.intent, "已处理")


# ---------------------------------------------------------------------------
# Tool dispatch (safe no-op stubs) — actual side effects live behind the
# platform's existing endpoints. The Copilot just *plans* the call.
# ---------------------------------------------------------------------------


_DRONE_COMMANDS = {
    "takeoff":         "drone.command.takeoff",
    "land":            "drone.command.land",
    "return_home":     "drone.command.rth",
    "hover":           "drone.command.hover",
    "goto_waypoint":   "drone.command.goto",
    "start_recording": "mission.recording.start",
    "stop_recording":  "mission.recording.stop",
}


def plan_tool_call(parsed: ParsedIntent, drone_id: str | None = None) -> dict[str, Any] | None:
    """Return a serializable representation of the platform call to invoke.

    The API layer decides whether to execute (based on user permission +
    drone state). We keep planning pure so the router is unit-testable.
    """
    if parsed.confidence < 0.6:
        return None
    cmd = _DRONE_COMMANDS.get(parsed.intent)
    if cmd:
        return {
            "tool": cmd,
            "drone_id": drone_id,
            "args": parsed.args,
        }
    if parsed.intent == "vision_query":
        return {"tool": "vision.detections.recent", "args": parsed.args}
    if parsed.intent == "generate_report":
        return {"tool": "report.generate", "args": parsed.args}
    if parsed.intent == "status":
        return {"tool": "agent.status", "args": {}}
    return None


def run_turn(text: str, *, drone_id: str | None = None) -> dict[str, Any]:
    """High-level convenience wrapper — parse + reply + plan in one call.

    Returns a dict compatible with the ``CopilotTurn`` table columns.
    """
    t0 = time.monotonic()
    parsed = parse_intent(text)
    tool_call = plan_tool_call(parsed, drone_id=drone_id)
    reply = render_reply(parsed)
    return {
        "intent": parsed.intent,
        "args": parsed.args,
        "confidence": parsed.confidence,
        "reply_text": reply,
        "tool_call": tool_call,
        "tool_result": None,     # left to caller (permission-gated)
        "status": "clarify" if parsed.intent == "unknown" else "ok",
        "latency_ms": round((time.monotonic() - t0) * 1000, 3),
    }
