"""SQLAlchemy async database setup for SkyMaster v0.1."""
from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://skymaster:skymaster@localhost:5432/skymaster",
)

# For in-memory SQLite, use StaticPool so all sessions share the same
# underlying connection (otherwise each connection gets its own empty
# in-memory database and cross-session data is invisible).
_engine_kwargs: dict = {"echo": False, "future": True, "pool_pre_ping": True}
if "sqlite" in DATABASE_URL and ":memory:" in DATABASE_URL:
    from sqlalchemy.pool import StaticPool
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

# SQLite dev mode: register stand-ins for PG server_default functions
# (now(), gen_random_uuid()) so INSERTs against a SQLite dev DB work
# without Postgres. Mirrors tests/conftest.py.
if "sqlite" in DATABASE_URL:
    import datetime as _dt
    import uuid as _uuid
    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(engine.sync_engine, "connect")
    def _register_pg_funcs(dbapi_conn, conn_record):  # noqa: ANN001
        dbapi_conn.create_function(
            "now", 0, lambda: _dt.datetime.utcnow().isoformat())
        dbapi_conn.create_function(
            "gen_random_uuid", 0, lambda: str(_uuid.uuid4()))

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
