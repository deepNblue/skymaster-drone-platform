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
    "sqlite+aiosqlite:////tmp/skymaster_test.db",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("USE_FAKE_REDIS", "true")
os.environ.setdefault("ENABLE_MISSION_WATCHER", "false")
os.environ.setdefault("ENABLE_TRAJECTORY_STORE", "false")
os.environ.setdefault("UOM_AUTO_APPROVE", "false")  # avoid pending racing tests
# AUTH_OPTIONAL not set globally - scenes_import uses optional auth


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


# SQLite doesn't have now() function - map to CURRENT_TIMESTAMP
from sqlalchemy import func as _sa_func


@compiles(_sa_func.now, "sqlite")
def _sqlite_now(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


# Patch text() server_defaults for SQLite (gen_random_uuid, etc.)
# Done at runtime in _ensure_schema and client fixtures

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# httpx >=0.28 removed the app= parameter from AsyncClient.
# Patch it back for test files that still use the old API.
_original_async_client_init = AsyncClient.__init__


def _patched_async_client_init(self, *args, **kwargs):
    if "app" in kwargs:
        app = kwargs.pop("app")
        kwargs.setdefault("transport", ASGITransport(app=app))
    return _original_async_client_init(self, *args, **kwargs)


AsyncClient.__init__ = _patched_async_client_init


_now_registered = False


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    """Ensure SQLite schema exists for every test (even those that bypass
    the `client` fixture and use AsyncSessionLocal directly)."""
    from app.db import engine, Base
    if "sqlite" in str(engine.url):
        # Register now() function for SQLite (used in server_default/onupdate)
        from sqlalchemy import event as _sa_event
        import datetime as _dt
        @_sa_event.listens_for(engine.sync_engine, "connect")
        def _register_now(dbapi_conn, conn_record):
            dbapi_conn.create_function("now", 0, lambda: _dt.datetime.utcnow().isoformat())
        from app.models import (  # noqa: F401
            user, organization, drone, mission, flight_log, audit_log,
            backup_code, login_event, password_reset_token,
            revoked_token, media_asset,
            flight_approval, vision_copilot, aaas, video_stream, model_marketplace,
            scene, scene_marketplace, scene_moderation, scene_job,
            community,
            copilot_workflow, copilot_workflow_run, copilot_workflow_schedule,
            community_playbook, approval_template, airspace_calendar,
            marketplace_monetization,
             scene_annotation,
             scene_frame,
         )
        try:
            # Patch ::jsonb, func.now(), gen_random_uuid() server_defaults for SQLite
            from sqlalchemy import text as sa_text, ColumnDefault, DefaultClause
            import uuid as _uuid
            for table in Base.metadata.sorted_tables:
                for col in table.columns:
                    sd = col.server_default
                    if sd is not None and hasattr(sd, 'arg'):
                        raw = sd.arg
                        raw_text = ""
                        if isinstance(raw, str):
                            raw_text = raw
                        elif hasattr(raw, 'text'):
                            raw_text = raw.text
                        elif hasattr(raw, 'name') and raw.name == 'now':
                            raw_text = "now()"

                        if '::jsonb' in raw_text:
                            col.server_default = DefaultClause(sa_text(raw_text.replace('::jsonb', '')))
                        elif 'gen_random_uuid' in raw_text:
                            col.server_default = None
                            if col.default is None:
                                col.default = ColumnDefault(lambda: _uuid.uuid4())
                        elif raw_text == 'now()' or (hasattr(raw, 'name') and raw.name == 'now'):
                            col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            # Clean all rows between tests (reverse dependency order)
            from sqlalchemy import delete
            async with engine.begin() as conn:
                for table in reversed(Base.metadata.sorted_tables):
                    await conn.execute(delete(table))
        except Exception as e:
            import warnings
            warnings.warn(f"_ensure_schema create_all failed: {e}")
    yield


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

    # Reset rate limiter bucket so tests don't trip 429 after many logins
    try:
        from app.services import rate_limit
        rate_limit._bucket.clear()
    except ImportError:
        pass

    from app.main import app  # local import — env vars must be set first

    # Ensure ORM schema exists for SQLite test DB. On Postgres this is
    # normally handled by alembic migrations; here we create_all as a
    # convenience for tests. Skip create_all if URL points to Postgres —
    # we assume alembic has already run.
    from app.db import engine, Base
    if "sqlite" in str(engine.url):
        # SQLite now() already registered by _ensure_schema fixture
        from app.models import (  # noqa: F401
            user, organization, drone, mission, flight_log, audit_log,
            backup_code, login_event, password_reset_token,
            revoked_token, media_asset,
            flight_approval, vision_copilot, aaas, video_stream, model_marketplace,
            scene, scene_marketplace, scene_moderation, scene_job,
            community,
            copilot_workflow, copilot_workflow_run, copilot_workflow_schedule,
            community_playbook, approval_template, airspace_calendar,
            marketplace_monetization,
             scene_annotation,
             scene_frame,
         )
        try:
            # Patch ::jsonb, func.now(), gen_random_uuid() server_defaults for SQLite
            from sqlalchemy import text as sa_text, ColumnDefault, DefaultClause
            import uuid as _uuid
            for table in Base.metadata.sorted_tables:
                for col in table.columns:
                    sd = col.server_default
                    if sd is not None and hasattr(sd, 'arg'):
                        raw = sd.arg
                        raw_text = ""
                        if isinstance(raw, str):
                            raw_text = raw
                        elif hasattr(raw, 'text'):
                            raw_text = raw.text
                        elif hasattr(raw, 'name') and raw.name == 'now':
                            raw_text = "now()"

                        if '::jsonb' in raw_text:
                            col.server_default = DefaultClause(sa_text(raw_text.replace('::jsonb', '')))
                        elif 'gen_random_uuid' in raw_text:
                            col.server_default = None
                            if col.default is None:
                                col.default = ColumnDefault(lambda: _uuid.uuid4())
                        elif raw_text == 'now()' or (hasattr(raw, 'name') and raw.name == 'now'):
                            col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))

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
            # Clean all data from previous test (file-based SQLite persists)
            if "sqlite" in str(engine.url) and "skymaster_test" in str(engine.url):
                from sqlalchemy import text
                async with engine.begin() as conn:
                    for t in reversed(Base.metadata.sorted_tables):
                        try:
                            await conn.execute(text(f'DELETE FROM "{t.name}"'))
                        except Exception:
                            pass

            # Ensure redis mock exists on app.state for tests that don't
            # have a real Redis connection (vision_stream tests etc.)
            if not hasattr(app.state, "redis") or app.state.redis is None:
                from unittest.mock import AsyncMock, MagicMock
                app.state.redis = MagicMock()
                app.state.redis.publish = AsyncMock(return_value=1)
                app.state.redis.get = AsyncMock(return_value=None)
                app.state.redis.set = AsyncMock(return_value=True)
                app.state.redis.delete = AsyncMock(return_value=1)
                app.state.redis.expire = AsyncMock(return_value=True)
                app.state.redis.close = AsyncMock()
            yield ac


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """A client with a pre-authenticated Bearer token.

    Creates a test user, logs in, and sets the Authorization header
    on the client so all subsequent requests are authenticated.
    """
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from uuid import uuid4

    email = f"test_{uuid4().hex[:8]}@example.com"
    pw = "StrongPassW0rd#"
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(),
            email=email,
            hashed_pw=hash_password(pw),
            role="admin",
        ))
        await s.commit()

    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": pw}
    )
    assert r.status_code == 200, f"auth_client login failed: {r.text}"
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
