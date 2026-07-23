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
        auto_approve: bool = True,
        approval_delay_s: float = 3.0,
    ) -> None:
        self.db_path = Path(db_path) if db_path else (
            Path(__file__).resolve().parents[2] / "data" / "uom.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_approve = auto_approve
        self.approval_delay_s = approval_delay_s
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
        if max_alt_m <= 0 or max_alt_m > 500:
            raise ValueError("max_alt_m must be in (0, 500]")
        if len(area_polygon) < 3:
            raise ValueError("area_polygon needs ≥3 points")

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
            r.approval_code = f"UOM-{int(r.submitted_at or 0)}-{report_id[:8]}"
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
            # Categorize reason to a bounded label to prevent cardinality
            # explosion; free-text goes into audit logs, not Prometheus.
            reason_lower = (reason or "").lower()
            if "geofence" in reason_lower or "no_fly" in reason_lower or "no-fly" in reason_lower:
                bucket = "geofence"
            elif "altitude" in reason_lower or "height" in reason_lower or "限高" in reason_lower:
                bucket = "altitude"
            elif "certificate" in reason_lower or "license" in reason_lower or "证" in reason_lower:
                bucket = "license"
            elif "weather" in reason_lower or "wind" in reason_lower or "天气" in reason_lower:
                bucket = "weather"
            elif "conflict" in reason_lower or "overlap" in reason_lower:
                bucket = "airspace_conflict"
            else:
                bucket = "other"
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
        """Every second, auto-approve PENDING reports older than delay_s."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(1.0)
                cutoff = time.time() - self.approval_delay_s
                to_approve = [
                    r.id for r in list(self._reports.values())
                    if r.status == ReportStatus.PENDING
                    and (r.submitted_at or 0) <= cutoff
                ]
                for rid in to_approve:
                    try:
                        await self.approve(rid, reviewer="auto-uom-mock")
                    except Exception:
                        logger.exception("auto-approve failed for %s", rid)
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
        _adapter = UOMAdapter(
            db_path=os.getenv("UOM_DB"),
            auto_approve=os.getenv("UOM_AUTO_APPROVE", "true").lower()
            in ("1", "true", "yes"),
            approval_delay_s=float(os.getenv("UOM_APPROVAL_DELAY_S", "3")),
        )
    return _adapter


def reset_for_tests() -> None:
    global _adapter
    _adapter = None
