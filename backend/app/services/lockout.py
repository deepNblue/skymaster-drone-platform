"""Brute-force lockout policy.

Configuration constants (kept module-level for easy monkeypatching in tests):

    MAX_FAILED   — number of consecutive failed logins before lockout
    LOCK_MINUTES — how long the account stays locked after tripping the limit

Behavior:
    on_success(user)  → reset counter + clear lock
    on_failure(user)  → increment; if ≥ MAX_FAILED, set locked_until = now + LOCK_MINUTES
    is_locked(user)   → True iff locked_until in the future
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User

MAX_FAILED = 5
LOCK_MINUTES = 15


def is_locked(user: "User") -> bool:
    lu = getattr(user, "locked_until", None)
    if lu is None:
        return False
    # Compare in UTC. locked_until is timezone-aware.
    if lu.tzinfo is None:
        lu = lu.replace(tzinfo=timezone.utc)
    return lu > datetime.now(tz=timezone.utc)


def on_success(user: "User") -> None:
    user.failed_login_count = 0
    user.locked_until = None


def on_failure(user: "User") -> None:
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= MAX_FAILED:
        user.locked_until = datetime.now(tz=timezone.utc) + timedelta(
            minutes=LOCK_MINUTES
        )
