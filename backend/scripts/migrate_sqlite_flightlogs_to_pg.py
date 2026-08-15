"""One-shot migration: copy flight_logs (and drones last state) from SQLite
dev.db into the new PostgreSQL instance. Idempotent-ish: only inserts rows
whose (time, drone_id) don't exist yet is complex; instead we copy all and
dedupe later if needed. Run once."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone

import asyncpg

SQLITE = "data/dev.db"

PG_DSN = "postgresql://postgres@127.0.0.1:5433/skymaster"


async def main() -> None:
    import aiosqlite

    conn = await asyncpg.connect(PG_DSN)
    pg_count = await conn.fetchval("SELECT count(*) FROM flight_logs")
    print("PG current flight_logs:", pg_count)

    async with aiosqlite.connect(SQLITE) as sdb:
        sdb.row_factory = aiosqlite.Row
        cur = await sdb.execute(
            "SELECT time, drone_id, lat, lng, alt, speed, battery_pct, flight_mode FROM flight_logs"
        )
        batch = []
        total = 0
        async for row in cur:
            t = row["time"]
            if isinstance(t, str):
                t = datetime.fromisoformat(t.replace("T", " ").split("+")[0].strip("Z"))
            batch.append((
                t, str(row["drone_id"]), row["lat"], row["lng"], row["alt"],
                row["speed"], row["battery_pct"], row["flight_mode"],
            ))
            if len(batch) >= 5000:
                await conn.executemany(
                    "INSERT INTO flight_logs (time, drone_id, lat, lng, alt, speed, battery_pct, flight_mode) "
                    "VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8)",
                    batch,
                )
                total += len(batch)
                batch = []
        if batch:
            await conn.executemany(
                "INSERT INTO flight_logs (time, drone_id, lat, lng, alt, speed, battery_pct, flight_mode) "
                "VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8)",
                batch,
            )
            total += len(batch)
    print("migrated rows:", total)
    pg_count2 = await conn.fetchval("SELECT count(*) FROM flight_logs")
    print("PG flight_logs now:", pg_count2)
    await conn.close()


asyncio.run(main())
