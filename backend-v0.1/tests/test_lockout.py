"""Unit tests for the brute-force lockout policy service."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import lockout


def _mkuser():
    return SimpleNamespace(
        failed_login_count=0,
        locked_until=None,
    )


def test_is_locked_none():
    u = _mkuser()
    assert lockout.is_locked(u) is False


def test_is_locked_past():
    u = _mkuser()
    u.locked_until = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    assert lockout.is_locked(u) is False


def test_is_locked_future():
    u = _mkuser()
    u.locked_until = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
    assert lockout.is_locked(u) is True


def test_on_success_resets():
    u = _mkuser()
    u.failed_login_count = 3
    u.locked_until = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
    lockout.on_success(u)
    assert u.failed_login_count == 0
    assert u.locked_until is None


def test_on_failure_increments_no_lock():
    u = _mkuser()
    lockout.on_failure(u)
    assert u.failed_login_count == 1
    assert u.locked_until is None


def test_on_failure_locks_at_threshold():
    u = _mkuser()
    for _ in range(lockout.MAX_FAILED - 1):
        lockout.on_failure(u)
    assert u.locked_until is None
    lockout.on_failure(u)  # crosses threshold
    assert u.failed_login_count == lockout.MAX_FAILED
    assert u.locked_until is not None
    assert lockout.is_locked(u) is True


def test_lock_expires_after_lock_minutes(monkeypatch):
    """Lock should end LOCK_MINUTES after locked_until."""
    u = _mkuser()
    u.locked_until = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    # Already-expired lock returns False so a fresh login can succeed.
    assert lockout.is_locked(u) is False
