"""Re-map flight_logs.drone_id from SQLite drone UUIDs to PG drone UUIDs (by SN)."""
import asyncio

import aiosqlite
import asyncpg

PG_DSN = "postgresql://postgres@127.0.0.1:5433/skymaster"


async def main() -> None:
    async with aiosqlite.connect("data/dev.db") as sdb:
        sdb.row_factory = aiosqlite.Row
        rows = await sdb.execute_fetchall("SELECT sn, id FROM drones")
        old_map = {r["sn"]: str(r["id"]) for r in rows}

    conn = await asyncpg.connect(PG_DSN)
    pg_rows = await conn.fetch("SELECT sn, id::text FROM drones")
    new_map = {r["sn"]: r["id"] for r in pg_rows}

    for sn, old_id in old_map.items():
        new_id = new_map.get(sn)
        if not new_id or old_id == new_id:
            continue
        n = await conn.fetchval(
            "SELECT count(*) FROM flight_logs WHERE drone_id=$1::uuid", old_id)
        await conn.execute(
            "UPDATE flight_logs SET drone_id=$1::uuid WHERE drone_id=$2::uuid",
            new_id, old_id)
        print(f"{sn}: remapped {n} logs {old_id[:8]} -> {new_id[:8]}")

    await conn.close()


asyncio.run(main())
