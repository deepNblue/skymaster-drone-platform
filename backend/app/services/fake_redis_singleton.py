"""In-process FakeRedis singleton for the dev stack.

When ``USE_FAKE_REDIS=true`` the mavlink connector, telemetry consumer, and
WebSocket pub/sub all need to share the SAME instance — because fakeredis
does not persist across separate FakeRedis() objects (each instance holds
its own in-memory server).

Usage
-----
    from app.services.fake_redis_singleton import get_redis, is_fake_enabled

    if is_fake_enabled():
        redis = get_redis()
    else:
        import redis.asyncio as aioredis
        redis = aioredis.from_url(REDIS_URL, decode_responses=True)
"""
from __future__ import annotations

import os
from typing import Any, Optional

_INSTANCE: Optional[Any] = None
_SERVER: Optional[Any] = None


def is_fake_enabled() -> bool:
    return os.getenv("USE_FAKE_REDIS", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_redis() -> Any:
    """Return the process-wide fakeredis async client.

    All callers within one Python process must call this to share the same
    in-memory server (streams, pub/sub, keys). Uses ``decode_responses=True``
    to match the real Redis client wiring elsewhere in the app.
    """
    global _INSTANCE, _SERVER
    if _INSTANCE is not None:
        return _INSTANCE

    # Import lazily so production installs without fakeredis still work.
    import fakeredis  # type: ignore[import-untyped]

    # A shared FakeServer means every FakeRedis() built from it points at
    # the same "backend" — required for xadd → xread across coroutines and
    # for publish → pubsub across the WS layer.
    _SERVER = fakeredis.FakeServer()
    _INSTANCE = fakeredis.aioredis.FakeRedis(
        server=_SERVER, decode_responses=True
    )
    return _INSTANCE


def reset_for_tests() -> None:
    """Drop the singleton — pytest fixtures use this between test cases."""
    global _INSTANCE, _SERVER
    _INSTANCE = None
    _SERVER = None
