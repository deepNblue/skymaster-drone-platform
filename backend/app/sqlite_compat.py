"""SQLite dev-mode compatibility layer.

On SQLite (dev/demo deployments without Postgres) we must:
  1. Register PG server_default stand-in SQL functions (now,
     gen_random_uuid) - done in app.db on connect.
  2. Swap PG-only text() server_defaults for Python-side defaults so
     INSERTs generate values client-side (SQLite cannot evaluate
     ``DEFAULT gen_random_uuid()`` for non-INTEGER primary keys).

This module implements (2). Call ``apply_sqlite_compat()`` once after
all models are imported (app.main lifespan and scripts do this).
Mirrors tests/conftest.py::_ensure_schema.
"""
from __future__ import annotations

import uuid as _uuid

from sqlalchemy import ColumnDefault, DefaultClause, text as _sa_text

_applied = False


def apply_sqlite_compat() -> bool:
    """Idempotent. Returns True if any column was patched.

    Safe to call multiple times (e.g. before all models are imported);
    already-patched columns are skipped, and the guard flag is only set
    once metadata actually contains tables.
    """
    global _applied

    from app.db import DATABASE_URL, Base
    if "sqlite" not in DATABASE_URL:
        _applied = True
        return False

    patched = 0
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None or not hasattr(sd, "arg"):
                # Already patched (server_default removed earlier)?
                if sd is None and col.default is not None:
                    continue
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
                    _sa_text(raw_text.replace("::jsonb", "")))
                patched += 1
            elif "gen_random_uuid" in raw_text:
                col.server_default = None
                if col.default is None:
                    col.default = ColumnDefault(lambda: _uuid.uuid4())
                patched += 1
            elif raw_text == "now()" or (
                    hasattr(raw, "name") and raw.name == "now"):
                col.server_default = DefaultClause(
                    _sa_text("CURRENT_TIMESTAMP"))
                patched += 1

    if len(Base.metadata.tables) > 0:
        _applied = True
    return patched > 0
