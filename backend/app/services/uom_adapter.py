"""UOM (Unmanned Aircraft Operation Management) Mock Adapter.

Simulates the flight-report approval workflow for the Nanning pilot,
per PRODUCT_SPEC §3.14 v2.0 Module ①.

State machine::

    DRAFT ─submit()→ PENDING ─approve()→ APPROVED ──takeoff_ok
      │                │
      │                └─reject()→ REJECTED
      └─cancel()→ CANCELLED

In prod this will proxy to the real 民航局 UOM API. Here we back it with
an in-memory dict + optional SQLite persistence so the dev stack can
demo the full compliance flow without external dependencies.

Approval delay is configurable (env ``UOM_APPROVAL_DELAY_S``, default 3s)
so demos can show pending → approved without waiting for real bureaucracy.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ReportStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class FlightReport:
    """A single flight-report submitted to the UOM system.

    Fields mirror the real Nanning UOM POST body (subset): pilot, aircraft,
    time window, area polygon, purpose, altitude limits.
    """

    id: str
    operator_id: str
    pilot_name: str
    aircraft_reg: str          # 民航局无人机注册号
    purpose: str               # 作业性质：航拍/巡检/农业/表演...
    area_polygon: list[list[float]]  # [[lng, lat], ...]
    max_alt_m: float
    start_ts: float            # unix seconds
    end_ts: float
    status: ReportStatus = ReportStatus.DRAFT
    submitted_at: Optional[float] = None
    reviewed_at: Optional[float] = None
    reviewer: Optional[str] = None
    reject_reason: Optional[str] = None
    approval_code: Optional[str] = None      # 类似 UOM 下发的审批号
    created_at: float = field(default_factory=time.time)


class UOMAdapter:
    """In-memory + SQLite-backed mock UOM.

    Thread-safe via asyncio.Lock. Background auto-approval task simulates
    UOM policy engine (env ``UOM_AUTO_APPROVE=true`` by default in dev).
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        auto_approve: Optional[bool] = None,
        approval_delay_s: Optional[float] = None,
        config: Optional[dict] = None,
    ) -> None:
        from app.services.uom_client import load_uom_config

        self.config = config or load_uom_config()
        report_cfg = self.config.get("report", {})
        self.db_path = Path(db_path) if db_path else (
            Path(__file__).resolve().parents[2] / "data" / "uom.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_approve = (
            auto_approve if auto_approve is not None
            else bool(report_cfg.get("auto_approve", True))
        )
        self.approval_delay_s = (
            approval_delay_s if approval_delay_s is not None
            else float(report_cfg.get("approval_delay_s", 3.0))
        )
        self.max_alt_m = float(report_cfg.get("max_alt_m", 500.0))
        self.min_polygon_points = int(report_cfg.get("min_polygon_points", 3))
        self.expire_after_end_s = float(report_cfg.get("expire_after_end_s", 3600))
        self.auto_expire_interval_s = float(
            report_cfg.get("auto_expire_interval_s", 1.0)
        )
        self.reviewer = str(report_cfg.get("reviewer", "auto-uom"))
        self.approval_code_prefix = str(
            report_cfg.get("approval_code_prefix", "UOM")
        )
        self.reject_reason_buckets = report_cfg.get("reject_reason_buckets", [])
        self._reports: dict[str, FlightReport] = {}
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()
        self._auto_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ----------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flight_reports (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_flight_reports_status "
            "ON flight_reports (status, created_at DESC)"
        )
        # Rehydrate.
        for row in self._conn.execute(
            "SELECT id, payload FROM flight_reports"
        ).fetchall():
            data = json.loads(row[1])
            data["status"] = ReportStatus(data["status"])
            self._reports[row[0]] = FlightReport(**data)

        if self.auto_approve:
            self._auto_task = asyncio.create_task(
                self._auto_approve_loop(), name="uom-auto-approve"
            )
        logger.info(
            "UOMAdapter started · db=%s · auto_approve=%s · rehydrated=%d",
            self.db_path, self.auto_approve, len(self._reports),
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._auto_task:
            self._auto_task.cancel()
            try:
                await asyncio.wait_for(self._auto_task, timeout=1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._conn:
            self._conn.close()
            self._conn = None

    # ----------------------------------------------------------------- CRUD
    async def submit(
        self,
        *,
        operator_id: str,
        pilot_name: str,
        aircraft_reg: str,
        purpose: str,
        area_polygon: list[list[float]],
        max_alt_m: float,
        start_ts: float,
        end_ts: float,
    ) -> FlightReport:
        if end_ts <= start_ts:
            raise ValueError("end_ts must be after start_ts")
        if max_alt_m <= 0 or max_alt_m > self.max_alt_m:
            raise ValueError(f"max_alt_m must be in (0, {self.max_alt_m:g}]")
        if len(area_polygon) < self.min_polygon_points:
            raise ValueError(
                f"area_polygon needs ≥{self.min_polygon_points} points"
            )

        report = FlightReport(
            id=str(uuid.uuid4()),
            operator_id=operator_id,
            pilot_name=pilot_name,
            aircraft_reg=aircraft_reg,
            purpose=purpose,
            area_polygon=area_polygon,
            max_alt_m=max_alt_m,
            start_ts=start_ts,
            end_ts=end_ts,
            status=ReportStatus.PENDING,
            submitted_at=time.time(),
        )
        async with self._lock:
            self._reports[report.id] = report
            self._persist(report)
        logger.info("UOM submit → %s (pilot=%s)", report.id, pilot_name)
        return report

    async def approve(self, report_id: str, reviewer: str = "auto-uom") -> FlightReport:
        async with self._lock:
            r = self._reports.get(report_id)
            if not r:
                raise KeyError(f"report {report_id} not found")
            if r.status != ReportStatus.PENDING:
                raise ValueError(f"cannot approve status={r.status}")
            r.status = ReportStatus.APPROVED
            r.reviewed_at = time.time()
            r.reviewer = reviewer
            r.approval_code = (
                f"{self.approval_code_prefix}-"
                f"{int(r.submitted_at or 0)}-{report_id[:8]}"
            )
            self._persist(r)
        logger.info("UOM approved → %s by %s", report_id, reviewer)
        try:
            from app.services.metrics import UOM_REPORTS
            UOM_REPORTS.inc(status="approved")
        except Exception:  # noqa: BLE001
            pass
        return r

    async def reject(
        self, report_id: str, reason: str, reviewer: str = "auto-uom"
    ) -> FlightReport:
        async with self._lock:
            r = self._reports.get(report_id)
            if not r:
                raise KeyError(f"report {report_id} not found")
            if r.status != ReportStatus.PENDING:
                raise ValueError(f"cannot reject status={r.status}")
            r.status = ReportStatus.REJECTED
            r.reviewed_at = time.time()
            r.reviewer = reviewer
            r.reject_reason = reason
            self._persist(r)
        logger.info("UOM rejected → %s (%s)", report_id, reason)
        try:
            from app.services.metrics import UOM_REPORTS, UOM_REJECTIONS
            UOM_REPORTS.inc(status="rejected")
            # Categorize reason to a bounded label (config-driven) to prevent
            # cardinality explosion; free-text stays in audit logs only.
            reason_lower = (reason or "").lower()
            bucket = "other"
            for rule in self.reject_reason_buckets:
                if any(str(kw).lower() in reason_lower
                       for kw in rule.get("keywords", [])):
                    bucket = str(rule.get("bucket", "other"))
                    break
            UOM_REJECTIONS.inc(reason=bucket)
        except Exception:  # noqa: BLE001
            pass
        return r

    async def cancel(self, report_id: str) -> FlightReport:
        async with self._lock:
            r = self._reports.get(report_id)
            if not r:
                raise KeyError(f"report {report_id} not found")
            if r.status not in (ReportStatus.DRAFT, ReportStatus.PENDING):
                raise ValueError(f"cannot cancel status={r.status}")
            r.status = ReportStatus.CANCELLED
            self._persist(r)
        return r

    async def expire_stale(
        self, now_ts: Optional[float] = None,
    ) -> list[FlightReport]:
        """Mark APPROVED reports past validity as EXPIRED (configurable grace).

        This closes the state-machine gap where ``EXPIRED`` was declared but
        never reached. Idempotent: only transitions APPROVED → EXPIRED.
        """
        now = now_ts if now_ts is not None else time.time()
        cutoff = now - self.expire_after_end_s
        changed: list[FlightReport] = []
        async with self._lock:
            for r in self._reports.values():
                if r.status == ReportStatus.APPROVED and r.end_ts <= cutoff:
                    r.status = ReportStatus.EXPIRED
                    r.reviewed_at = r.reviewed_at or now
                    self._persist(r)
                    changed.append(r)
        if changed:
            logger.info("UOM expired %d reports (cutoff=%.0f)", len(changed), cutoff)
        return changed

    async def get(self, report_id: str) -> Optional[FlightReport]:
        return self._reports.get(report_id)

    async def list_all(
        self,
        status: Optional[ReportStatus] = None,
        operator_id: Optional[str] = None,
    ) -> list[FlightReport]:
        """List reports, optionally filtered by status and/or operator_id.

        ``operator_id`` filter is what enables the v1.0 multi-tenant
        isolation: viewers/operators only see their own org's reports;
        admins pass ``operator_id=None`` to see everything.
        """
        items = list(self._reports.values())
        if status:
            items = [r for r in items if r.status == status]
        if operator_id:
            items = [r for r in items if r.operator_id == operator_id]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items

    async def check_ready_for_takeoff(
        self, mission_area: list[list[float]], now_ts: Optional[float] = None,
    ) -> tuple[bool, Optional[FlightReport], str]:
        """Return (ok, matching_report, reason).

        Called from mission_dispatcher before a real dispatch — verifies
        an APPROVED report covers this mission's polygon + current time.
        """
        # Only expire against real time: a simulated ``now_ts`` in the future
        # must not mutate persisted state for unrelated tests/callers.
        if now_ts is None:
            await self.expire_stale()
        now = now_ts or time.time()
        for r in self._reports.values():
            if r.status != ReportStatus.APPROVED:
                continue
            if not (r.start_ts <= now <= r.end_ts):
                continue
            if not _polygon_contains(r.area_polygon, mission_area):
                continue
            return True, r, "ok"
        return False, None, "no approved flight report covers this mission"

    # ----------------------------------------------------------------- internals
    def _persist(self, r: FlightReport) -> None:
        if not self._conn:
            return
        data = asdict(r)
        data["status"] = r.status.value
        self._conn.execute(
            "INSERT OR REPLACE INTO flight_reports (id, payload, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            (r.id, json.dumps(data), r.status.value, r.created_at),
        )
        self._conn.commit()

    async def _auto_approve_loop(self) -> None:
        """Periodically auto-approve stale PENDING and expire stale APPROVED."""
        interval = max(0.1, min(1.0, self.auto_expire_interval_s))
        try:
            while not self._stop.is_set():
                await asyncio.sleep(interval)
                now = time.time()
                cutoff = now - self.approval_delay_s
                to_approve = [
                    r.id for r in list(self._reports.values())
                    if r.status == ReportStatus.PENDING
                    and (r.submitted_at or 0) <= cutoff
                ]
                for rid in to_approve:
                    try:
                        await self.approve(rid, reviewer=self.reviewer)
                    except Exception:
                        logger.exception("auto-approve failed for %s", rid)
                await self.expire_stale(now)
        except asyncio.CancelledError:
            pass


def _polygon_contains(
    outer: list[list[float]], inner: list[list[float]]
) -> bool:
    """Check every ``inner`` vertex lies inside ``outer`` (2D ray casting).

    Both polygons in [lng, lat] order. Good enough for mock: at v2.0-real
    we swap in Shapely + srid.
    """
    if not inner:
        return False
    return all(_point_in_poly(pt, outer) for pt in inner)


def _point_in_poly(pt: list[float], poly: list[list[float]]) -> bool:
    x, y = pt[0], pt[1]
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


# ----------------------------------------------------------------- singleton
_adapter: Optional[UOMAdapter] = None


def get_uom() -> UOMAdapter:
    global _adapter
    if _adapter is None:
        from app.services.uom_client import load_uom_config

        cfg = load_uom_config()
        env_auto = os.getenv("UOM_AUTO_APPROVE")
        auto_approve = (
            env_auto.strip().lower() in ("1", "true", "yes")
            if env_auto is not None else None
        )
        env_delay = os.getenv("UOM_APPROVAL_DELAY_S")
        approval_delay_s = float(env_delay) if env_delay else None
        _adapter = UOMAdapter(
            db_path=os.getenv("UOM_DB"),
            auto_approve=auto_approve,
            approval_delay_s=approval_delay_s,
            config=cfg,
        )
    return _adapter


def reset_for_tests() -> None:
    global _adapter
    _adapter = None
