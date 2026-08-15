"""Seed 3 demo Drone rows for the dev telemetry stack.

Each drone carries meta {"sysid": N, "udp_port": 1455x} consumed by the
backend's START_TELEMETRY_STACK wiring. Idempotent (matches on sn).

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
    # sn, label, sysid, udp_port, model
    ("FAKE-SIM-01", "仿真机-01", 1, 14550, "FakeQuad-1"),
    ("FAKE-SIM-02", "仿真机-02", 2, 14551, "FakeQuad-2"),
    ("FAKE-SIM-03", "仿真机-03", 3, 14552, "FakeQuad-3"),
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
        for sn, label, sysid, port, model in DRONES:
            row = (await s.execute(
                select(Drone).where(Drone.sn == sn))).scalar_one_or_none()
            if row is None:
                row = Drone(
                    sn=sn,
                    org_id=org_id,
                    model=model,
                    protocol="mavlink",
                    status="idle",
                    meta={"label": label, "sysid": sysid,
                          "udp_port": port},
                )
                s.add(row)
                created += 1
            else:
                row.meta = {"label": label, "sysid": sysid,
                            "udp_port": port}
                row.org_id = row.org_id or org_id
                row.status = row.status or "idle"
                kept += 1
        await s.commit()
        rows = (await s.execute(select(Drone))).scalars().all()
    print(f"[seed_drones] created={created} kept={kept} total={len(rows)}")
    for r in rows:
        print(f"  - {r.sn} id={r.id} meta={getattr(r, 'meta', None)}")


asyncio.run(main())
