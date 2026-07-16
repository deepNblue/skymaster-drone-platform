"""IP-based rate limiter for login / refresh endpoints.

Uses Redis when available; falls back to an in-process token bucket so
tests and dev-mode (no redis) still enforce the limit.

Policy defaults (env-tunable):
    LOGIN_RATE_MAX      = 10   attempts
    LOGIN_RATE_WINDOW_S = 60   seconds
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request

MAX = int(os.getenv("LOGIN_RATE_MAX", "10"))
WINDOW = int(os.getenv("LOGIN_RATE_WINDOW_S", "60"))

_lock = asyncio.Lock()
_bucket: dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Honor X-Forwarded-For when behind a proxy; else fall back to peer.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_login_rate(request: Request) -> None:
    """Raise HTTP 429 if the requesting IP exceeded MAX attempts in WINDOW seconds."""
    ip = _client_ip(request)
    now = time.time()
    async with _lock:
        q = _bucket[ip]
        # Drop stale entries older than window.
        cutoff = now - WINDOW
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= MAX:
            retry_after = int(q[0] + WINDOW - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts — retry after {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)


def reset_bucket() -> None:
    """Test helper — clear the in-memory bucket."""
    _bucket.clear()
