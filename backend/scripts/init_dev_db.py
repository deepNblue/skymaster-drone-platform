"""One-shot dev DB initializer: SQLite schema creation with PG-type
compiler overrides (mirrors tests/conftest.py). Usage:
    DATABASE_URL=sqlite+aiosqlite:///data/dev.db .venv/bin/python scripts/init_dev_db.py
"""
import asyncio
import datetime as dt
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import BigInteger, func as _sa_func, event as _sa_event  # noqa: E402
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    ARRAY as _PgARRAY,
    INET,
    JSONB,
    TIMESTAMP,
    UUID as _PgUUID,
)
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(_PgUUID, "sqlite")
def _sqlite_uuid(element, compiler, **kw):
    return "CHAR(36)"


@compiles(BigInteger, "sqlite")
def _sqlite_bigint(element, compiler, **kw):
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


@compiles(_PgARRAY, "sqlite")
def _sqlite_array(element, compiler, **kw):
    return "TEXT"


@compiles(_sa_func.now, "sqlite")
def _sqlite_now(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


from app.db import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (register all tables)


def _register_pg_funcs(dbapi_conn, conn_record):
    """SQLite stand-ins for PG server_default functions."""
    dbapi_conn.create_function(
        "now", 0, lambda: dt.datetime.utcnow().isoformat())
    dbapi_conn.create_function(
        "gen_random_uuid", 0, lambda: str(uuid.uuid4()))


_sa_event.listens_for(engine.sync_engine, "connect")(_register_pg_funcs)


def _patch_server_defaults() -> None:
    """Swap PG-only server_defaults for SQLite-compatible equivalents
    (same recipe as tests/conftest.py::_ensure_schema)."""
    from sqlalchemy import text as sa_text, ColumnDefault, DefaultClause
    import uuid as _uuid
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None or not hasattr(sd, "arg"):
                continue
            raw = sd.arg
            raw_text = ""
            if isinstance(raw, str):
                raw_text = raw
            elif hasattr(raw, "text"):
                raw_text = raw.text
            elif hasattr(raw, "name") and raw.name == "now":
                raw_text = "now()"
            if "::jsonb" in raw_text:
                col.server_default = DefaultClause(
                    sa_text(raw_text.replace("::jsonb", "")))
            elif "gen_random_uuid" in raw_text:
                col.server_default = None
                if col.default is None:
                    col.default = ColumnDefault(lambda: _uuid.uuid4())
            elif raw_text == "now()" or (
                    hasattr(raw, "name") and raw.name == "now"):
                col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))


async def main() -> None:
    _patch_server_defaults()
    ok, fail = 0, []
    for name in Base.metadata.tables:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda c, n=name: Base.metadata.tables[n].create(
                        c, checkfirst=True))
            ok += 1
        except Exception as ex:  # noqa: BLE001
            fail.append((name, str(ex).split("\n")[0][:80]))
    for n, e in fail:
        print(f"FAIL: {n} -> {e}")
    from sqlalchemy import text
    async with engine.connect() as conn:
        n = len((await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )).fetchall())
    print(f"dev DB ready: {ok}/{len(Base.metadata.tables)} created, "
          f"{n} tables present at {engine.url}")


asyncio.run(main())
