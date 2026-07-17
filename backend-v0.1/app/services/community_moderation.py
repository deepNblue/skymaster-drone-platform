"""Community moderation — lightweight keyword-based content filter.

Per PRODUCT_SPEC §3.18: "LLM 前置审核 + 关键词库 + 举报队列 + 人工兜底".
This module implements the fast keyword-library layer. The LLM layer
can be layered on top later (call moderate_llm() if configured).

Design goals:
* Deterministic + auditable (returns which keyword tripped the filter).
* No external network calls in the fast path.
* Handles obvious涉军涉密/暴恐/黄赌毒/spam terms typical for a UAV
  community forum operated in mainland China. Real deployments should
  swap this list for a maintained regulatory-grade blocklist.
"""
from __future__ import annotations

from dataclasses import dataclass


# --- Keyword library --------------------------------------------------------
# Broken into categories for future admin-panel management. Keep lowercase.
_MILITARY = {
    "涉军", "军事机密", "军工", "军演", "武器化", "改装弹药",
    "投弹", "军事无人机", "反无系统",
}
_VIOLENT = {
    "暴恐", "恐怖袭击", "炸弹", "爆炸物", "武器制造", "袭击",
    "杀人", "枪支",
}
_ILLEGAL = {
    "毒品", "冰毒", "海洛因", "走私", "赌博",
}
_SPAM = {
    "加微信", "加v信", "私聊出售", "刷单兼职", "www.bet",
}
_PORN = {
    "色情", "情色", "porn", "裸聊",
}

_BLOCK_MAP: dict[str, set[str]] = {
    "military": _MILITARY,
    "violent": _VIOLENT,
    "illegal": _ILLEGAL,
    "spam": _SPAM,
    "porn": _PORN,
}

# --- Public API -------------------------------------------------------------


@dataclass(frozen=True)
class ModerationResult:
    """Outcome of a moderation pass.

    Attributes
    ----------
    status:  'approved' | 'pending' | 'rejected'
    reason:  human-readable Chinese explanation (empty when approved)
    matched: list of (category, keyword) pairs that tripped the filter
    """
    status: str
    reason: str
    matched: list[tuple[str, str]]

    @property
    def approved(self) -> bool:
        return self.status == "approved"


def moderate_text(text: str) -> ModerationResult:
    """Fast keyword scan on title + body.

    Rules:
    * Any hit in _MILITARY/_VIOLENT/_ILLEGAL/_PORN → 'rejected'.
    * Any hit in _SPAM → 'pending' (queued for human review, not
      auto-rejected because false positives are cheap to fix).
    * No hits → 'approved'.

    Case-insensitive, whitespace-tolerant.
    """
    if not text:
        return ModerationResult(
            status="rejected",
            reason="内容为空",
            matched=[],
        )
    haystack = text.lower()
    matched: list[tuple[str, str]] = []
    hard_reject = False
    soft_hold = False
    for category, kws in _BLOCK_MAP.items():
        for kw in kws:
            if kw.lower() in haystack:
                matched.append((category, kw))
                if category == "spam":
                    soft_hold = True
                else:
                    hard_reject = True

    if hard_reject:
        cats = sorted({c for c, _ in matched if c != "spam"})
        return ModerationResult(
            status="rejected",
            reason=f"命中受限关键词类别: {', '.join(cats)}",
            matched=matched,
        )
    if soft_hold:
        return ModerationResult(
            status="pending",
            reason="疑似营销/垃圾信息，待人工审核",
            matched=matched,
        )
    return ModerationResult(status="approved", reason="", matched=[])


def moderate_post(title: str, body: str) -> ModerationResult:
    """Convenience helper: scan title AND body, take the strictest outcome."""
    t_res = moderate_text(title or "")
    b_res = moderate_text(body or "")
    # Rejection dominates > pending > approved.
    for res in (t_res, b_res):
        if res.status == "rejected":
            return res
    for res in (t_res, b_res):
        if res.status == "pending":
            return res
    return ModerationResult(status="approved", reason="", matched=[])
