"""Reference GPU worker · v2.1 T2.3.

Long-running poll loop:

    while True:
        job = POST /api/v1/scene-jobs/_worker/claim
        if job is None: sleep(POLL_SECONDS); continue
        try:
            heartbeat every HB_SECONDS in background task
            run_executor(job.kind, job.scene_id) → result
            POST .../complete with result
        except Exception as e:
            POST .../fail with traceback

This module is the *skeleton*; the actual COLMAP/gsplat integration is
still stubbed via ``NoOpExecutor``. Replace the executor branches with
real subprocess calls to nerfstudio-gsplat or the Inria trainer as
those bindings land.

Environment
-----------
* ``SKYMASTER_API_URL``      — API base URL (e.g. http://skymaster-api:8000)
* ``SKYMASTER_WORKER_TOKEN`` — bearer token, matches API server
* ``WORKER_ID``              — unique per pod (K8s downward API metadata.name)
* ``WORKER_KINDS``           — comma-separated kinds this worker will accept
* ``POLL_SECONDS``           — how often to poll queue when empty (default 5)
* ``HEARTBEAT_SECONDS``      — lease refresh interval (default 60)
* ``LEASE_SECONDS``          — lease TTL per claim (default 300)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
import traceback
from pathlib import Path
from typing import Any, Optional

import httpx


log = logging.getLogger(__name__)

API_URL = os.environ.get("SKYMASTER_API_URL", "http://skymaster-api:8000")
TOKEN = os.environ.get("SKYMASTER_WORKER_TOKEN", "")
WORKER_ID = os.environ.get("WORKER_ID", "worker-local")
KINDS = [k.strip() for k in os.environ.get("WORKER_KINDS", "colmap,training").split(",") if k.strip()]
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "5"))
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "60"))
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "300"))

HEARTBEAT_FILE = Path("/tmp/heartbeat")


def _touch_heartbeat() -> None:
    """Write a heartbeat file for k8s liveness probe."""
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except OSError:
        pass


class WorkerClient:
    def __init__(self, base: str, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base,
            headers={"X-Worker-Token": token},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def claim(self) -> Optional[dict]:
        r = await self._client.post("/api/v1/scene-jobs/_worker/claim", json={
            "worker_id": WORKER_ID,
            "kinds": KINDS,
            "lease_seconds": LEASE_SECONDS,
        })
        r.raise_for_status()
        return r.json() if r.content else None

    async def heartbeat(self, job_id: str) -> None:
        r = await self._client.post(
            f"/api/v1/scene-jobs/_worker/{job_id}/heartbeat",
            json={"worker_id": WORKER_ID, "lease_seconds": LEASE_SECONDS, "running": True},
        )
        r.raise_for_status()

    async def complete(self, job_id: str, result: dict) -> None:
        r = await self._client.post(
            f"/api/v1/scene-jobs/_worker/{job_id}/complete",
            json={"worker_id": WORKER_ID, **result},
        )
        r.raise_for_status()

    async def fail(self, job_id: str, error: str) -> None:
        try:
            r = await self._client.post(
                f"/api/v1/scene-jobs/_worker/{job_id}/fail",
                json={"worker_id": WORKER_ID, "error": error[:4000]},
            )
            r.raise_for_status()
        except Exception:  # noqa: BLE001
            log.exception("failed to report failure — leasing will auto-expire")


# ---------------------------------------------------------------------------
# Executor stubs
# ---------------------------------------------------------------------------


async def _run_colmap(scene_id: str) -> dict:
    """Placeholder COLMAP SfM.

    Real impl:
        1. Download frames from S3 to /var/scratch/<scene_id>/images/
        2. subprocess `colmap automatic_reconstructor --workspace_path=...`
        3. Parse output n_points from sparse/0/points3D.txt
    """
    log.info("running COLMAP for scene %s (stub)", scene_id)
    await asyncio.sleep(2)  # simulate work
    return {"n_points": 32_000}


async def _run_training(scene_id: str) -> dict:
    """Placeholder gsplat training.

    Real impl:
        1. Load COLMAP result from S3
        2. subprocess `ns-train splatfacto --data=...`
        3. Parse final PSNR from training log
        4. Upload output .ply to S3
    """
    log.info("running gsplat training for scene %s (stub)", scene_id)
    await asyncio.sleep(2)
    return {"n_gaussians": 500_000, "psnr": 28.5}


async def _run_export(scene_id: str) -> dict:
    log.info("running export for scene %s (stub)", scene_id)
    await asyncio.sleep(1)
    return {}


EXECUTORS = {
    "colmap": _run_colmap,
    "training": _run_training,
    "export": _run_export,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


class Worker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._client = WorkerClient(API_URL, TOKEN)

    def request_stop(self, *_: Any) -> None:
        log.info("worker %s received stop signal", WORKER_ID)
        self._stop.set()

    async def _heartbeat_loop(self, job_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self._client.heartbeat(job_id)
                _touch_heartbeat()
            except Exception:  # noqa: BLE001
                log.warning("heartbeat failed for %s", job_id, exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _process_job(self, job: dict) -> None:
        job_id = job["id"]
        kind = job["kind"]
        scene_id = job["scene_id"]
        log.info("claimed job %s kind=%s scene=%s", job_id, kind, scene_id)

        hb_stop = asyncio.Event()
        hb_task = asyncio.create_task(self._heartbeat_loop(job_id, hb_stop))
        try:
            fn = EXECUTORS.get(kind)
            if fn is None:
                await self._client.fail(job_id, f"no executor for kind {kind!r}")
                return
            result = await fn(scene_id)
            await self._client.complete(job_id, result)
            log.info("job %s completed", job_id)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            log.exception("job %s failed", job_id)
            await self._client.fail(job_id, tb)
        finally:
            hb_stop.set()
            await hb_task

    async def run(self) -> None:
        log.info(
            "worker %s starting, api=%s kinds=%s",
            WORKER_ID, API_URL, KINDS,
        )
        _touch_heartbeat()
        try:
            while not self._stop.is_set():
                try:
                    job = await self._client.claim()
                except Exception:  # noqa: BLE001
                    log.warning("claim failed, retrying", exc_info=True)
                    await asyncio.sleep(POLL_SECONDS)
                    continue

                _touch_heartbeat()
                if job is None:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=POLL_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                    continue

                await self._process_job(job)
        finally:
            await self._client.close()
            log.info("worker %s exited cleanly", WORKER_ID)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not TOKEN:
        log.error("SKYMASTER_WORKER_TOKEN not set — refusing to start")
        raise SystemExit(2)

    worker = Worker()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    try:
        loop.run_until_complete(worker.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
