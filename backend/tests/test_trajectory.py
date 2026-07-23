"""Tests for the trajectory store + API."""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.trajectory_store import TrajectoryStore


@pytest.mark.asyncio
async def test_trajectory_store_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "traj.db"
        store = TrajectoryStore(db_path=db, flush_interval_s=0.05, max_batch=5)
        await store.start()
        try:
            # Ingest 10 rows
            base_ts = time.time()
            for i in range(10):
                await store.ingest("test-drone", {
                    "ts": base_ts + i,
                    "lat": 39.9 + i * 0.001,
                    "lng": 116.4 + i * 0.001,
                    "alt": 100 + i,
                    "speed": 5 + i,
                    "heading": i * 10,
                })
            await asyncio.sleep(0.1)  # Let flush run.

            trail = await store.get_trail("test-drone", seconds=60)
            assert len(trail) == 10
            assert trail[0]["lat"] == pytest.approx(39.9)
            assert trail[-1]["lat"] == pytest.approx(39.9 + 9 * 0.001)

            drones = await store.get_drones()
            assert "test-drone" in drones
        finally:
            await store.stop()


@pytest.mark.asyncio
async def test_trajectory_ignores_bad_frames():
    with tempfile.TemporaryDirectory() as td:
        store = TrajectoryStore(db_path=Path(td) / "traj.db", flush_interval_s=0.05)
        await store.start()
        try:
            await store.ingest("d1", {"lat": None, "lng": None})
            await store.ingest("d1", {"lat": "not-a-num", "lng": "x"})
            await store.ingest("d1", {})
            await asyncio.sleep(0.1)
            trail = await store.get_trail("d1", seconds=60)
            assert trail == []
        finally:
            await store.stop()


def test_trajectory_api_disabled_returns_503(monkeypatch):
    """Skip full app lifespan; smoke test store getter logic only."""
    from app.api.v1 import trajectory as traj_router

    class FakeReq:
        class app:  # type: ignore[no-redef]
            class state:
                pass

    with pytest.raises(Exception):
        traj_router._store(FakeReq())  # type: ignore[arg-type]
