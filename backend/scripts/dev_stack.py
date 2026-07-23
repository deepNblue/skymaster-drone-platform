"""SkyMaster dev stack — one-command in-memory backend.

Runs FastAPI + TelemetryConsumer + MavlinkConnector against fakeredis and
SQLite in-memory so we can drive the full pipeline without Docker / real DB.

Usage
-----
    .venv/bin/python scripts/dev_stack.py

Then in another shell:
    .venv/bin/python scripts/fake_drone.py --system-id 1 --port 14550

The browser can hit http://localhost:8000/docs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path

# Ensure the project root is importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- env defaults
_DEFAULTS = {
    # In-memory demo mode uses fakeredis and skips DB persistence so we can
    # showcase the FakeDrone → MavlinkConnector → Redis Stream → WebSocket loop
    # without any external services. Set NO_DB=false + a real DATABASE_URL to
    # enable persistence.
    "NO_DB": "true",
    "DATABASE_URL": "sqlite+aiosqlite:////tmp/skymaster-dev.db",
    "USE_FAKE_REDIS": "true",
    "REDIS_URL": "redis://localhost:6379/0",  # unused when fake redis on
    "MAVLINK_ENDPOINT": "udpin:0.0.0.0:14550",
    "JWT_SECRET": "dev-stack-secret-key-min-32-chars-xxx",
    "JWT_ALG": "HS256",
    "JWT_EXPIRE_MIN": "60",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "dev",
    "MINIO_SECRET_KEY": "devsecret",
    "LLM_API_KEY": "dev-dummy",
    "LLM_BASE_URL": "http://localhost:9",  # unreachable → agent will error gracefully
    "MEDIAMTX_API_URL": "http://localhost:9997",
    "START_TELEMETRY_CONSUMER": "false",  # requires DB — off by default
    "START_MAVLINK_CONNECTOR": "true",
    "SIM_MODE": "true",
    "SIM_DRONES": "1:15001,2:15002",
    "TELEMETRY_BATCH_SIZE": "10",
    "TELEMETRY_FLUSH_MS": "500",
    "DEBUG": "true",
    "PYTHONUNBUFFERED": "1",
    "LOG_LEVEL": "DEBUG",
}
for k, v in _DEFAULTS.items():
    os.environ.setdefault(k, v)


# Root logging so background task exceptions show up in the console.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)


BANNER = r"""
╔══════════════════════════════════════════════════════════════════════╗
║  🚀  SkyMaster Dev Stack Ready                                       ║
║                                                                      ║
║      API   → http://localhost:8000/docs                              ║
║      Login → admin@example.com / admin123                            ║
║      MAV   → udp://0.0.0.0:14550 (send fake_drone.py)                ║
║                                                                      ║
║  Ctrl+C to stop.                                                     ║
╚══════════════════════════════════════════════════════════════════════╝
"""


async def _init_db_and_seed() -> None:
    """Create all tables in the DB and seed 1 org + 1 admin (idempotent)."""
    from datetime import datetime
    from uuid import uuid4

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import (
        ARRAY as PGARRAY,
        INET,
        JSONB,
        UUID as PGUUID,
    )
    from sqlalchemy.ext.compiler import compiles

    # ---- SQLite compatibility shim -----------------------------------------
    # The ORM was written for PostgreSQL. On SQLite we transparently rewrite
    # PG-specific column types via the @compiles decorator (documented API).
    @compiles(PGUUID, "sqlite")  # noqa: E501
    def _uuid_sqlite(element, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    @compiles(JSONB, "sqlite")
    def _jsonb_sqlite(element, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(PGARRAY, "sqlite")
    def _array_sqlite(element, compiler, **kw):  # noqa: ARG001
        return "TEXT"

    @compiles(INET, "sqlite")
    def _inet_sqlite(element, compiler, **kw):  # noqa: ARG001
        return "TEXT"

    # Geometry (PostGIS) → TEXT on SQLite
    try:
        from geoalchemy2 import Geography, Geometry

        @compiles(Geography, "sqlite")
        def _geog_sqlite(element, compiler, **kw):  # noqa: ARG001
            return "TEXT"

        @compiles(Geometry, "sqlite")
        def _geom_sqlite(element, compiler, **kw):  # noqa: ARG001
            return "TEXT"
    except ImportError:
        pass

    from app.db import engine, AsyncSessionLocal, Base
    import app.models  # ensure ORM classes are imported so metadata is complete
    from app.services.auth import hash_password

    # Wipe any leftover file so we get a fresh schema on each run.
    db_url = os.environ["DATABASE_URL"]
    if db_url.startswith("sqlite+aiosqlite:////"):
        path = db_url.replace("sqlite+aiosqlite:////", "/")
        try:
            os.remove(path)
            print(f"[dev-stack] removed stale DB file {path}")
        except FileNotFoundError:
            pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import inspect

        def _tables(sync_conn):
            return sorted(inspect(sync_conn).get_table_names())

        tables = await conn.run_sync(_tables)
        print(f"[dev-stack] created tables ({len(tables)}): {tables}")

    async with AsyncSessionLocal() as sess:
        try:
            from app.models.organization import Organization
            from app.models.user import User
        except ImportError:
            print("[dev-stack] Could not import Organization / User ORM.")
            return

        existing = await sess.execute(
            select(User).where(User.email == "admin@example.com")
        )
        if existing.scalar_one_or_none() is not None:
            print("[dev-stack] admin already seeded")
            return

        now = datetime.utcnow()
        org = Organization(
            id=uuid4(),
            name="Dev Org",
            tenant_type="standard",
            created_at=now,
        )
        sess.add(org)
        await sess.flush()

        admin = User(
            id=uuid4(),
            org_id=org.id,
            email="admin@example.com",
            hashed_pw=hash_password("admin123"),
            role="admin",
            created_at=now,
        )
        sess.add(admin)
        await sess.commit()
        print(f"[dev-stack] seeded org={org.id} admin={admin.email}")


async def _run_server() -> None:
    import uvicorn

    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    print(BANNER)
    await server.serve()


async def main() -> None:
    if os.getenv("NO_DB", "").lower() not in ("1", "true", "yes"):
        try:
            await _init_db_and_seed()
        except Exception:
            print("[dev-stack] DB init/seed failed:")
            traceback.print_exc()
    else:
        print("[dev-stack] NO_DB=true — skipping DB init/seed (in-memory demo mode)")

    await _run_server()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[dev-stack] bye 👋")
