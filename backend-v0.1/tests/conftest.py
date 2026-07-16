"""Shared pytest fixtures for SkyMaster v0.1 smoke tests.

Env vars are set at import time (before app modules load) so that
`app.config.Settings` and `app.db.engine` see safe defaults without
requiring a real Postgres/Redis instance running.
"""
from __future__ import annotations

import os

# --- Provide safe defaults BEFORE any `app.*` import ---------------------
# Tests use SQLite in-memory (or file) instead of Postgres.
# Individual tests requiring Postgres skip themselves via pytest.mark.skipif
# on DATABASE_URL. See tests/test_admin.py for reference.
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("USE_FAKE_REDIS", "true")
os.environ.setdefault("ENABLE_MISSION_WATCHER", "false")
os.environ.setdefault("ENABLE_TRAJECTORY_STORE", "false")
os.environ.setdefault("UOM_AUTO_APPROVE", "false")  # avoid pending racing tests


# --- SQLite compat for Postgres-specific types ---------------------------
# The models use dialects.postgresql.UUID/JSONB/INET/TIMESTAMP because
# production runs on Postgres. Tests use SQLite; register compiler
# overrides so create_all() works on SQLite too.
from sqlalchemy.dialects.postgresql import UUID as _PgUUID, JSONB, INET, TIMESTAMP  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(_PgUUID, "sqlite")
def _sqlite_uuid(element, compiler, **kw):
    return "CHAR(36)"


@compiles(BigInteger, "sqlite")
def _sqlite_bigint(element, compiler, **kw):
    # SQLite only supports AUTOINCREMENT on INTEGER PRIMARY KEY (not BIGINT).
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(element, compiler, **kw):
    return "TEXT"


@compiles(INET, "sqlite")
def _sqlite_inet(element, compiler, **kw):
    return "TEXT"


@compiles(TIMESTAMP, "sqlite")
def _sqlite_ts(element, compiler, **kw):
    return "TIMESTAMP"


# T11.2: community_playbooks uses postgres ARRAY(String) for tags —
# lower to plain TEXT on SQLite. The service layer stores/reads as
# JSON string when running on SQLite.
from sqlalchemy.dialects.postgresql import ARRAY as _PgARRAY  # noqa: E402


@compiles(_PgARRAY, "sqlite")
def _sqlite_array(element, compiler, **kw):
    return "TEXT"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Yield an httpx.AsyncClient bound to the FastAPI app via ASGI transport.

    The app is imported lazily so env-var overrides above take effect first.
    Also resets module-level singletons so tests don't leak state, and
    creates the SQLite schema on first use.
    """
    # Reset singletons — UOM/GeoFence hold module-level state that leaks
    # across tests when the app is re-instantiated in the same process.
    # For UOM we also delete the on-disk SQLite so approved reports from
    # earlier tests don't spoof compliance checks in later tests.
    import os
    for _f in ("data/uom.db", "data/uom.db-journal"):
        if os.path.exists(_f):
            try:
                os.remove(_f)
            except OSError:
                pass
    try:
        from app.services import uom_adapter, geofence
        uom_adapter._adapter = None
        geofence._engine = None
    except ImportError:
        pass

    from app.main import app  # local import — env vars must be set first

    # Ensure ORM schema exists for SQLite test DB. On Postgres this is
    # normally handled by alembic migrations; here we create_all as a
    # convenience for tests. Skip create_all if URL points to Postgres —
    # we assume alembic has already run.
    from app.db import engine, Base
    if "sqlite" in str(engine.url):
        from app.models import (  # noqa: F401
            user, organization, drone, mission, flight_log, audit_log,
            backup_code, login_event, password_reset_token,
            revoked_token, media_asset,
            flight_approval, vision_copilot, aaas, video_stream, model_marketplace,
            scene, scene_marketplace, scene_moderation, scene_job,
            community,
            copilot_workflow, copilot_workflow_run, copilot_workflow_schedule,
            community_playbook, approval_template,
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:  # noqa: BLE001
            # Some tables use Postgres-specific defaults like
            # gen_random_uuid() that SQLite can't parse. Rewrite offending
            # server_defaults to None just for the test session, then retry.
            def _sd_text(sd):
                if sd is None:
                    return ""
                arg = getattr(sd, "arg", None)
                if arg is None:
                    return ""
                txt = getattr(arg, "text", None)
                if isinstance(txt, str):
                    return txt
                if isinstance(arg, str):
                    return arg
                return ""

            import uuid as _uuid

            for t in Base.metadata.sorted_tables:
                for col in t.columns:
                    if col.server_default is not None:
                        txt = _sd_text(col.server_default)
                        if "gen_random_uuid" in txt:
                            # SQLite can't gen_random_uuid — provide a
                            # Python-side default so INSERTs succeed.
                            col.server_default = None
                            if col.default is None:
                                col.default = None  # placeholder
                                # SQLAlchemy Column.default expects a
                                # ColumnDefault; use ScalarElementColumnDefault
                                from sqlalchemy import ColumnDefault
                                col.default = ColumnDefault(lambda: _uuid.uuid4())
                        elif "::jsonb" in txt or "now()" in txt.lower() or "array[" in txt.lower():
                            col.server_default = None
                    if col.onupdate is not None:
                        onup_txt = _sd_text(col.onupdate)
                        if "now()" in onup_txt:
                            col.onupdate = None
            for t in Base.metadata.sorted_tables:
                try:
                    async with engine.begin() as conn:
                        await conn.run_sync(lambda c, tt=t: tt.create(c, checkfirst=True))
                except Exception:
                    pass

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        async with app.router.lifespan_context(app):
            yield ac
