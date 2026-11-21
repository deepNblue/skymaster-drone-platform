"""R22 · audit export service tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models.audit_log import AuditLog
from app.services.audit_export import (
    ExportFilter,
    export_csv,
    export_gbft,
    integrity_report,
)


@pytest.fixture
async def db_session():
    # Async in-memory SQLite; audit_logs table dropped/created per test.
    # NOTE: audit_logs uses postgres-specific types (JSONB, PgUUID, INET).
    # For the export service tests we sidestep this by exercising in-memory
    # objects only — no INSERT/SELECT against SQLite would map cleanly.
    # Instead each test constructs AuditLog() directly and hits a small
    # mock async session. Kept as a marker for future integration tests.
    yield None


class FakeStreamResult:
    """Mimics ``result = await db.stream_scalars(stmt)``.

    Yields the pre-loaded rows in insertion order (matches our
    ``ORDER BY ts ASC, id ASC`` invariant since we pre-sort).
    """

    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for r in self._rows:
            yield r


class FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def stream_scalars(self, stmt):  # noqa: ARG002 — we ignore filters
        return FakeStreamResult(self._rows)


def _make_row(
    idx: int,
    action: str = "resource.read",
    ts: datetime | None = None,
    actor_role: str = "audit_officer",
    prev_hash: str | None = None,
    curr_hash: str | None = None,
    sig_hex: str | None = None,
    sig_key_id: str | None = None,
) -> AuditLog:
    row = AuditLog(
        action=action,
        actor_role=actor_role,
        resource=f"res-{idx}",
        diff={"field": f"val-{idx}"},
        prev_hash=prev_hash,
        curr_hash=curr_hash or hashlib.sha256(f"row-{idx}".encode()).hexdigest(),
        sig_hex=sig_hex,
        sig_key_id=sig_key_id,
    )
    row.id = idx
    row.ts = ts or datetime(2026, 7, 13, 10, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=idx)
    row.actor_id = uuid4()
    row.ip = None
    row.ua = None
    return row


def _rows_with_chain(n: int, *, signed: bool = True):
    """Build ``n`` rows whose curr_hash → next.prev_hash forms a valid chain."""
    out = []
    prev = None
    for i in range(1, n + 1):
        h = hashlib.sha256(f"row-{i}".encode()).hexdigest()
        out.append(_make_row(
            i, prev_hash=prev, curr_hash=h,
            sig_hex=(f"deadbeef{i:04x}" * 8 if signed else None),
            sig_key_id="v1" if signed else None,
        ))
        prev = h
    return out


# ---------------------------------------------------------------------------


def test_export_csv_contains_all_columns_and_bom():
    rows = _rows_with_chain(3)
    session = FakeSession(rows)

    out = asyncio.run(export_csv(session, ExportFilter()))
    assert out.startswith(b"\xef\xbb\xbf"), "CSV must start with UTF-8 BOM for Excel"
    text = out.decode("utf-8-sig")
    lines = text.splitlines()
    header = lines[0].split(",")
    for col in ["id", "ts", "actor_role", "action", "curr_hash", "sig_hex", "sig_key_id"]:
        assert col in header, f"missing column {col!r}"
    assert len(lines) == 4, "1 header + 3 rows"


def test_export_gbft_has_header_then_records():
    rows = _rows_with_chain(2)
    out = asyncio.run(export_gbft(FakeSession(rows), ExportFilter()))
    lines = out.decode("utf-8").rstrip("\n").split("\n")
    assert len(lines) == 3, "1 header + 2 records"
    header = json.loads(lines[0])
    assert header["type"] == "gbft-header"
    assert header["record_count"] == 2
    assert header["version"] == "gbft-v1"
    assert header["hash_chain_start"] is None  # first row's prev_hash is None
    for rec_line in lines[1:]:
        rec = json.loads(rec_line)
        assert rec["type"] == "gbft-record"
        assert "curr_hash" in rec and rec["curr_hash"]
        assert rec["sig_hex"] and rec["sig_key_id"] == "v1"


def test_integrity_report_detects_break():
    # Craft a chain, then mutate one row's prev_hash to break linkage
    rows = _rows_with_chain(5)
    rows[3].prev_hash = "0" * 64  # broken here (id=4)
    rep = asyncio.run(integrity_report(FakeSession(rows), ExportFilter()))
    assert rep.total == 5
    assert rep.hash_chain_ok is False
    assert rep.hash_chain_break_at == 4  # id of first bad row
    assert rep.signed_count == 5
    assert rep.unsigned_count == 0


def test_integrity_report_ok_when_valid():
    rows = _rows_with_chain(4)
    rep = asyncio.run(integrity_report(FakeSession(rows), ExportFilter()))
    assert rep.total == 4
    assert rep.hash_chain_ok is True
    assert rep.hash_chain_break_at is None


def test_integrity_report_counts_unsigned():
    rows = _rows_with_chain(3, signed=False)
    rep = asyncio.run(integrity_report(FakeSession(rows), ExportFilter()))
    assert rep.signed_count == 0
    assert rep.unsigned_count == 3


def test_export_filter_limit_is_clamped():
    """A caller can't ask for more than MAX_ROWS."""
    from app.services.audit_export import MAX_ROWS_PER_EXPORT

    flt = ExportFilter(limit=MAX_ROWS_PER_EXPORT * 10)
    assert flt.clamp_limit() == MAX_ROWS_PER_EXPORT

    flt2 = ExportFilter(limit=0)
    assert flt2.clamp_limit() == 1  # min 1


def test_export_csv_encodes_diff_as_json_string():
    rows = _rows_with_chain(1)
    out = asyncio.run(export_csv(FakeSession(rows), ExportFilter()))
    text = out.decode("utf-8-sig")
    lines = text.splitlines()
    # header line + 1 data line
    data = lines[1]
    # diff column should contain valid JSON
    assert '{"field": "val-1"}' in data or '"{""field"": ""val-1""}"' in data
