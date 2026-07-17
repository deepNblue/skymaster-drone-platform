"""Audit log export service — R22.

Provides bulk export of audit_logs for the 审计员 (audit officer) role.

Two output formats:

* ``csv`` — for spreadsheets / general analytics.
* ``gbft`` — 等保三级要求的国标审计接口格式（GB/T 20945-2013 类
  "网络安全审计数据交换格式" 简化子集）：一行 JSON per record，含 hash-chain
  头 + SM2 签名字段，便于第三方审计事务所离线核验。

The service is read-only and streams to a `StringIO` / `BytesIO` so
large exports (>10万行) don't blow up memory. Callers wire it to a
`StreamingResponse` at the API layer.

Design constraints
------------------

1. **Never mutate audit_logs**. Export is a pure read.
2. **Preserve hash chain metadata** (prev_hash / curr_hash / sig_hex /
   sig_key_id) verbatim so downstream tools can re-verify the chain.
3. **Filter safely** — audit officers may filter by time range, actor
   role, or action; every filter is a whitelisted column with type
   coercion so no free-form SQL surfaces.
4. **Deterministic ordering** — always sort by (ts asc, id asc) so
   exports are reproducible across calls.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


ALLOWED_FORMATS = frozenset({"csv", "gbft"})

# Hard cap so an accidental unbounded export doesn't OOM the box.
MAX_ROWS_PER_EXPORT = 500_000


@dataclass
class ExportFilter:
    """Whitelisted filter set. All fields optional; None → no filter."""

    ts_from: Optional[datetime] = None  # inclusive
    ts_to: Optional[datetime] = None  # exclusive
    actor_role: Optional[str] = None
    action: Optional[str] = None
    actor_id: Optional[UUID] = None
    limit: int = MAX_ROWS_PER_EXPORT

    def clamp_limit(self) -> int:
        return max(1, min(self.limit, MAX_ROWS_PER_EXPORT))


def _row_to_public(row: AuditLog) -> dict:
    """Serialize one audit row into a dict. Timestamps → ISO 8601 UTC."""
    ts_iso = row.ts.astimezone(timezone.utc).isoformat() if row.ts else None
    return {
        "id": row.id,
        "ts": ts_iso,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "actor_role": row.actor_role,
        "action": row.action,
        "resource": row.resource,
        "diff": row.diff,
        "ip": str(row.ip) if row.ip else None,
        "ua": row.ua,
        "prev_hash": row.prev_hash,
        "curr_hash": row.curr_hash,
        "sig_hex": row.sig_hex,
        "sig_key_id": row.sig_key_id,
    }


async def _stream_rows(
    db: AsyncSession, flt: ExportFilter
) -> AsyncIterator[AuditLog]:
    """Yield rows one-at-a-time (SQLAlchemy async server-side streaming)."""
    stmt = select(AuditLog).order_by(AuditLog.ts.asc(), AuditLog.id.asc())
    conds = []
    if flt.ts_from:
        conds.append(AuditLog.ts >= flt.ts_from)
    if flt.ts_to:
        conds.append(AuditLog.ts < flt.ts_to)
    if flt.actor_role:
        conds.append(AuditLog.actor_role == flt.actor_role)
    if flt.action:
        conds.append(AuditLog.action == flt.action)
    if flt.actor_id:
        conds.append(AuditLog.actor_id == flt.actor_id)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.limit(flt.clamp_limit())

    # Use stream_scalars so rows aren't all loaded at once.
    result = await db.stream_scalars(stmt)
    async for row in result:
        yield row


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


CSV_FIELDS = [
    "id", "ts", "actor_id", "actor_role", "action", "resource",
    "ip", "ua", "diff_json",
    "prev_hash", "curr_hash", "sig_hex", "sig_key_id",
]


async def export_csv(db: AsyncSession, flt: ExportFilter) -> bytes:
    """Return the full CSV as bytes (utf-8 with BOM for Excel compat)."""
    buf = io.StringIO()
    # BOM so Excel opens as UTF-8 by default
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    async for row in _stream_rows(db, flt):
        pub = _row_to_public(row)
        pub["diff_json"] = (
            json.dumps(pub.pop("diff"), ensure_ascii=False, sort_keys=True)
            if pub.get("diff") is not None
            else ""
        )
        # Drop unknown keys so DictWriter doesn't choke
        writer.writerow({k: pub.get(k, "") for k in CSV_FIELDS})
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# GBFT (等保三级 · 国标审计交换格式，简化子集)
# ---------------------------------------------------------------------------


GBFT_HEADER_VERSION = "gbft-v1"


def _gbft_header(count: int, flt: ExportFilter, first_prev: str | None) -> dict:
    return {
        "type": "gbft-header",
        "version": GBFT_HEADER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": count,
        "filter": {
            "ts_from": flt.ts_from.isoformat() if flt.ts_from else None,
            "ts_to": flt.ts_to.isoformat() if flt.ts_to else None,
            "actor_role": flt.actor_role,
            "action": flt.action,
        },
        "hash_chain_start": first_prev,
        "notes": (
            "Records are ordered (ts asc, id asc). Verify the hash chain by "
            "linking each row's prev_hash to the previous row's curr_hash; "
            "then verify SM2 sig_hex under the corresponding sig_key_id "
            "public key exported via /crypto/sm2/public/{key_id}."
        ),
    }


async def export_gbft(db: AsyncSession, flt: ExportFilter) -> bytes:
    """JSONL export — one record per line + header line."""
    buf = io.StringIO()
    # We stream, but need the header to include record_count → collect once.
    rows: list[AuditLog] = []
    async for row in _stream_rows(db, flt):
        rows.append(row)
    first_prev = rows[0].prev_hash if rows else None
    header = _gbft_header(count=len(rows), flt=flt, first_prev=first_prev)
    buf.write(json.dumps(header, ensure_ascii=False) + "\n")
    for row in rows:
        payload = {
            "type": "gbft-record",
            **_row_to_public(row),
        }
        buf.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Chain integrity self-check (used by the API to include a verdict)
# ---------------------------------------------------------------------------


@dataclass
class ChainIntegrityReport:
    total: int
    hash_chain_ok: bool
    hash_chain_break_at: Optional[int]  # audit row id where linkage broke
    signed_count: int
    unsigned_count: int


async def integrity_report(
    db: AsyncSession, flt: ExportFilter
) -> ChainIntegrityReport:
    prev: Optional[str] = None
    signed = 0
    unsigned = 0
    total = 0
    break_at: Optional[int] = None
    async for row in _stream_rows(db, flt):
        total += 1
        if row.sig_hex:
            signed += 1
        else:
            unsigned += 1
        # Chain linkage: this row's prev_hash must equal the previous row's curr_hash
        if prev is not None and row.prev_hash != prev and break_at is None:
            break_at = row.id
        prev = row.curr_hash
    return ChainIntegrityReport(
        total=total,
        hash_chain_ok=(break_at is None),
        hash_chain_break_at=break_at,
        signed_count=signed,
        unsigned_count=unsigned,
    )
