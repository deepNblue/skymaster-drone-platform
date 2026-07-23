"""End-to-end smoke test — mirrors scripts/e2e_smoke.sh but via pytest.

Skipped unless the env var RUN_INTEGRATION=1 is set, since it needs a live
API + Postgres + (optionally) SITL container.

Run with:
    RUN_INTEGRATION=1 API_BASE=http://localhost:8000 \\
        pytest -q tests/test_e2e_smoke.py -m integration
"""
from __future__ import annotations

import os
import time

import httpx
import pytest


API_BASE = os.getenv("API_BASE", "http://localhost:8000")
SEED_EMAIL = os.getenv("SEED_EMAIL", "admin@test.local")
SEED_PASS = os.getenv("SEED_PASS", "admin123")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="integration test — set RUN_INTEGRATION=1 to run",
    ),
]


async def _wait_for_health(client: httpx.AsyncClient, timeout_s: int = 30) -> None:
    deadline = time.time() + timeout_s
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            r = await client.get(f"{API_BASE}/api/v1/health")
            if r.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001 — retry on any network error
            last_exc = exc
        time.sleep(1)
    raise RuntimeError(
        f"API did not become healthy within {timeout_s}s (last error: {last_exc})"
    )


async def _seed_db() -> None:
    """Idempotent org+admin seed — same logic as scripts/db_seed.py."""
    from scripts.db_seed import seed  # local import so unit tests don't need it

    await seed()


@pytest.mark.asyncio
async def test_e2e_smoke_flow() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1) health
        await _wait_for_health(client)

        # 2) seed
        await _seed_db()

        # 3) login
        r = await client.post(
            f"{API_BASE}/api/v1/auth/login",
            json={"email": SEED_EMAIL, "password": SEED_PASS},
        )
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        assert token
        headers = {"Authorization": f"Bearer {token}"}

        # 4) create drone SITL-01 (idempotent by sn)
        r = await client.post(
            f"{API_BASE}/api/v1/drones",
            headers=headers,
            json={
                "sn": "SITL-01",
                "model": "SITL",
                "protocol": "mavlink",
                "metadata": {"mavlink_endpoint": "udpin:0.0.0.0:14550"},
            },
        )
        assert r.status_code in (200, 201), f"drone create failed: {r.text}"
        drone_id = r.json()["id"]
        assert drone_id

        # 5) create mission with 3 waypoints
        r = await client.post(
            f"{API_BASE}/api/v1/missions",
            headers=headers,
            json={
                "name": "SITL smoke mission",
                "drone_id": drone_id,
                "template": "waypoint",
                "waypoints": [
                    {"lat": 39.9042, "lng": 116.4074, "alt": 60, "speed": 5},
                    {"lat": 39.9052, "lng": 116.4084, "alt": 60, "speed": 5},
                    {"lat": 39.9042, "lng": 116.4074, "alt": 60, "speed": 5},
                ],
            },
        )
        assert r.status_code in (200, 201), f"mission create failed: {r.text}"
        mission_id = r.json()["id"]
        assert mission_id

        # 6) validate mission → ok=true
        r = await client.post(
            f"{API_BASE}/api/v1/missions/{mission_id}/validate", headers=headers
        )
        assert r.status_code == 200, f"validate failed: {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"validation not ok: {body}"

        # 7) GET /drones non-empty
        r = await client.get(f"{API_BASE}/api/v1/drones", headers=headers)
        assert r.status_code == 200
        assert r.json().get("total", 0) >= 1

        # 8) GET /missions non-empty
        r = await client.get(f"{API_BASE}/api/v1/missions", headers=headers)
        assert r.status_code == 200
        assert r.json().get("total", 0) >= 1
