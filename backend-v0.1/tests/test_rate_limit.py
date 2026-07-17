"""Unit tests for IP-based login rate limiter."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import rate_limit


def _mkreq(ip: str = "1.2.3.4"):
    return SimpleNamespace(
        headers={},
        client=SimpleNamespace(host=ip),
    )


def _mkreq_xff(xff: str):
    return SimpleNamespace(
        headers={"x-forwarded-for": xff},
        client=SimpleNamespace(host="127.0.0.1"),
    )


@pytest.mark.asyncio
async def test_rate_limit_under_threshold(monkeypatch):
    rate_limit.reset_bucket()
    monkeypatch.setattr(rate_limit, "MAX", 5)
    for _ in range(5):
        await rate_limit.check_login_rate(_mkreq("10.0.0.1"))


@pytest.mark.asyncio
async def test_rate_limit_exceeds(monkeypatch):
    from fastapi import HTTPException
    rate_limit.reset_bucket()
    monkeypatch.setattr(rate_limit, "MAX", 3)
    monkeypatch.setattr(rate_limit, "WINDOW", 60)
    for _ in range(3):
        await rate_limit.check_login_rate(_mkreq("10.0.0.2"))
    with pytest.raises(HTTPException) as exc:
        await rate_limit.check_login_rate(_mkreq("10.0.0.2"))
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


@pytest.mark.asyncio
async def test_rate_limit_per_ip_isolated(monkeypatch):
    rate_limit.reset_bucket()
    monkeypatch.setattr(rate_limit, "MAX", 2)
    await rate_limit.check_login_rate(_mkreq("10.0.0.10"))
    await rate_limit.check_login_rate(_mkreq("10.0.0.10"))
    # Different IP should have its own budget.
    await rate_limit.check_login_rate(_mkreq("10.0.0.11"))
    await rate_limit.check_login_rate(_mkreq("10.0.0.11"))


@pytest.mark.asyncio
async def test_rate_limit_xff_honored(monkeypatch):
    from fastapi import HTTPException
    rate_limit.reset_bucket()
    monkeypatch.setattr(rate_limit, "MAX", 2)
    real_ip = "203.0.113.99"
    await rate_limit.check_login_rate(_mkreq_xff(f"{real_ip}, 10.0.0.1"))
    await rate_limit.check_login_rate(_mkreq_xff(f"{real_ip}, 10.0.0.1"))
    with pytest.raises(HTTPException):
        await rate_limit.check_login_rate(_mkreq_xff(f"{real_ip}, 10.0.0.1"))
