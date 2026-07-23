"""Community content moderation — keyword filter for SkyMaster.

v2.2 E4 MVP:
- Simple deterministic keyword blocklist (Chinese + English)
- Pre-defined categories: 涉政, 涉恐, 涉黄, 违法, 侵权, 广告垃圾
- Return: status (approved / rejected / pending) + reason string
- Pending = needs manual review (contains suspicious terms but not blocked outright)

Next version can add LLM-based moderation.
"""
from __future__ import annotations

from dataclasses import dataclass


# Blocked keywords — will be extended via admin UI in v2.2.1
BLOCKLIST = {
    # Political sensitive
    "涉政": [
        # intentionally left blank in open source; admin can add via config
    ],
    # Terrorism / violence
    "涉恐": [
        "isis", "al-qaeda", "taliban",
    ],
    # Pornography / adult content
    "涉黄": [
        "porn", "sex", "adult", "xxx", "escort",
    ],
    # Illegal goods / services
    "违法": [
        "drugs", "weapon", "gun", "fake id",
    ],
    # Copyright / trademark infringement
    "侵权": [
        "crack", "keygen", "pirate", "torrent",
    ],
    # Spam / low quality advertising
    "垃圾": [
        "viagra", "cialis", "buy cheap", "free trial", "click here",
    ],
}

# Suspicious terms that go to manual review (not auto-block)
PENDLIST = [
    "free", "discount", "win", "winner", "click", "link in bio",
]


@dataclass
class ModerationResult:
    status: str  # "approved" | "rejected" | "pending"
    reason: str | None = None


def moderate_content(text: str) -> ModerationResult:
    """Moderate a piece of community content (post / comment).

    Returns:
    - `approved` → ok to publish immediately
    - `rejected` → auto-block, do not publish
    - `pending` → ok to save but needs manual review before public
    """
    text_lower = text.lower()
    blocked_categories: list[str] = []

    for cat, keywords in BLOCKLIST.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                blocked_categories.append(f"{cat}({kw})")

    if blocked_categories:
        reason = f"Blocked: {', '.join(blocked_categories)}"
        return ModerationResult(status="rejected", reason=reason)

    # Check pending terms
    pending_count = 0
    for kw in PENDLIST:
        if kw.lower() in text_lower:
            pending_count += 1

    if pending_count >= 3:
        reason = f"Suspicious: {pending_count} terms need manual review"
        return ModerationResult(status="pending", reason=reason)

    # All clear
    return ModerationResult(status="approved", reason=None)
