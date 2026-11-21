"""Lightweight SQLite-backed trajectory store for dev / demo mode.

TimescaleDB is the production choice (see :mod:`app.services.telemetry_consumer`),
but it requires postgres:16 + timescaledb extension in docker. For the dev
stack we want zero-infra persistence — this module writes every telemetry
frame into ``data/telemetry.db`` and exposes a query API for the frontend
trajectory trail feature.

Schema
------
    CREATE TABLE trajectory (
        drone_id TEXT   NOT NULL,
        ts       REAL   NOT NULL,   -- unix seconds
        lat      REAL,
        lng      REAL,
        alt      REAL,
        speed    REAL,
        heading  REAL,
        PRIMARY KEY (drone_id, ts)
    );
    CREATE INDEX ix_trajectory_drone_ts ON trajectory (drone_id, ts DESC);
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "telemetry.db"


class TrajectoryStore:
    """Thread-safe SQLite trajectory store with async-friendly wrappers.

    Writes happen in a background asyncio task, batched every 500ms or when
    the buffer exceeds 200 rows.
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        flush_interval_s: float = 0.5,
        max_batch: int = 200,
        retention_hours: float = 24.0,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.flush_interval_s = flush_interval_s
        self.max_batch = max_batch
        self.retention_hours = retention_hours
        self._buffer: list[tuple] = []
        self._lock = asyncio.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._closed = False

    # ------------------------------------------------------------------ init
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trajectory (
                drone_id TEXT NOT NULL,
                ts REAL NOT NULL,
                lat REAL, lng REAL, alt REAL, speed REAL, heading REAL,
                PRIMARY KEY (drone_id, ts)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_trajectory_drone_ts "
            "ON trajectory (drone_id, ts DESC)"
        )
        return conn

    async def start(self) -> None:
        """Open DB + start background flush task."""
        self._conn = self._connect()
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("TrajectoryStore started · db=%s", self.db_path)

    async def stop(self) -> None:
        self._closed = True
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await asyncio.wait_for(self._flush_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        await self._flush_now()
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        logger.info("TrajectoryStore stopped")

    # --------------------------------------------------------------- ingest
    async def ingest(self, drone_id: str, msg: dict[str, Any]) -> None:
        """Buffer a single telemetry frame."""
        try:
            lat = _num(msg.get("lat") or msg.get("latitude"))
            lng = _num(msg.get("lng") or msg.get("longitude"))
            if lat is None or lng is None:
                return
            row = (
                str(drone_id),
                float(msg.get("ts") or time.time()),
                lat,
                lng,
                _num(msg.get("alt") or msg.get("altitude")),
                _num(msg.get("speed") or msg.get("groundspeed")),
                _num(msg.get("heading")),
            )
            should_flush = False
            async with self._lock:
                self._buffer.append(row)
                if len(self._buffer) >= self.max_batch:
                    should_flush = True
            if should_flush:
                await self._flush_now()
        except Exception:
            logger.exception("TrajectoryStore.ingest failed")

    async def _flush_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self.flush_interval_s)
                await self._flush_now()
        except asyncio.CancelledError:
            pass

    async def _flush_now(self) -> None:
        if not self._conn:
            return
        async with self._lock:
            if not self._buffer:
                return
            rows = self._buffer
            self._buffer = []
        # Write in an executor so we don't block the event loop on I/O.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._write_rows, rows)

    def _write_rows(self, rows: list[tuple]) -> None:
        assert self._conn is not None
        try:
            self._conn.executemany(
                "INSERT OR IGNORE INTO trajectory "
                "(drone_id, ts, lat, lng, alt, speed, heading) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            logger.debug("TrajectoryStore wrote %d rows", len(rows))
            # Cheap retention: every ~50 flushes purge old data.
            if hash(rows[0][1]) % 50 == 0:
                cutoff = time.time() - self.retention_hours * 3600
                self._conn.execute("DELETE FROM trajectory WHERE ts < ?", (cutoff,))
        except sqlite3.Error:
            logger.exception("TrajectoryStore write failed")

    # ---------------------------------------------------------------- query
    async def get_trail(
        self, drone_id: str, seconds: float = 300.0, limit: int = 2000,
    ) -> list[dict]:
        """Return the trail (list of {ts, lat, lng, alt, ...}) for a drone.

        ``seconds`` controls the time window (default: last 5 min).
        """
        if not self._conn:
            return []
        # Flush pending writes so the query sees fresh data.
        await self._flush_now()
        cutoff = time.time() - seconds
        loop = asyncio.get_running_loop()

        def _q() -> list[dict]:
            assert self._conn is not None
            cur = self._conn.execute(
                "SELECT ts, lat, lng, alt, speed, heading FROM trajectory "
                "WHERE drone_id = ? AND ts >= ? "
                "ORDER BY ts ASC LIMIT ?",
                (str(drone_id), cutoff, int(limit)),
            )
            cols = ("ts", "lat", "lng", "alt", "speed", "heading")
            return [dict(zip(cols, row)) for row in cur.fetchall()]

        return await loop.run_in_executor(None, _q)

    async def get_drones(self) -> list[str]:
        """List all drone_ids that have any recorded trajectory."""
        if not self._conn:
            return []
        loop = asyncio.get_running_loop()

        def _q() -> list[str]:
            assert self._conn is not None
            cur = self._conn.execute(
                "SELECT DISTINCT drone_id FROM trajectory ORDER BY drone_id"
            )
            return [row[0] for row in cur.fetchall()]

        return await loop.run_in_executor(None, _q)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- singleton
_store: Optional[TrajectoryStore] = None


def get_store() -> TrajectoryStore:
    global _store
    if _store is None:
        _store = TrajectoryStore(db_path=os.getenv("TRAJECTORY_DB"))
    return _store
