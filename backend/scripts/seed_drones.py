"""Seed demo Drone rows for the dev telemetry stack.

MAVLink drones carry meta {"sysid": N, "udp_port": 1455x} consumed by the
backend's MavlinkConnector wiring. DJI drones carry protocol="dji" and
meta.dji_device_sn, consumed by DJICloudConnector. Idempotent (matches on sn).

Usage:
    DATABASE_URL=sqlite+aiosqlite:///data/dev.db \\
    .venv/bin/python -m scripts.seed_drones
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db import AsyncSessionLocal  # noqa: E402
from app.models.drone import Drone  # noqa: E402
from app.models.organization import Organization  # noqa: E402

# AFTER models registered on Base.metadata:
from app.sqlite_compat import apply_sqlite_compat  # noqa: E402

apply_sqlite_compat()

DRONES = [
    # sn, protocol, model, status, meta
    ("FAKE-SIM-01", "mavlink", "FakeQuad-1", "idle",
     {"label": "仿真机-01", "sysid": 1, "udp_port": 14550}),
    ("FAKE-SIM-02", "mavlink", "FakeQuad-2", "idle",
     {"label": "仿真机-02", "sysid": 2, "udp_port": 14551}),
    ("FAKE-SIM-03", "mavlink", "FakeQuad-3", "idle",
     {"label": "仿真机-03", "sysid": 3, "udp_port": 14552}),
    ("DJI-M300-01", "dji", "Matrice 300 RTK", "offline",
     {"label": "12309检察巡逻机", "model": "M300 RTK",
      "dji_device_sn": "MOCKM300-01", "dji_gateway_sn": "MOCKDOCK001"}),
]


async def main() -> None:
    created, kept = 0, 0
    async with AsyncSessionLocal() as s:
        # attach drones to the seeded org (db_seed.py creates TestOrg)
        org = (await s.execute(
            select(Organization).order_by(
                Organization.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        org_id = org.id if org else None
        for sn, protocol, model, status, meta in DRONES:
            row = (await s.execute(
                select(Drone).where(Drone.sn == sn))).scalar_one_or_none()
            if row is None:
                row = Drone(
                    sn=sn,
                    org_id=org_id,
                    model=model,
                    protocol=protocol,
                    status=status,
                    meta=meta,
                )
                s.add(row)
                created += 1
            else:
                row.meta = meta
                row.protocol = protocol
                row.org_id = row.org_id or org_id
                kept += 1
        await s.commit()
        rows = (await s.execute(select(Drone))).scalars().all()
    print(f"[seed_drones] created={created} kept={kept} total={len(rows)}")
    for r in rows:
        print(f"  - {r.sn} id={r.id} meta={getattr(r, 'meta', None)}")


asyncio.run(main())
