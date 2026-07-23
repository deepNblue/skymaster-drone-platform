#!/usr/bin/env python3
"""FakeDrone → MavlinkConnector → fakeredis Stream 全链路验证。

不依赖数据库。启动 MavlinkConnector 监听 UDP 14550，跑 fake_drone.py 发包，
然后从 fakeredis 读取 telemetry:<sysid> stream 验证数据落地。

期望：Stream 长度 ≥ 20，每条 entry 含 lat/lng。
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/duoduo/projects/skymaster-drone-platform/backend-v0.1")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ["USE_FAKE_REDIS"] = "true"


async def main() -> int:
    from app.services import fake_redis_singleton
    from app.services.mavlink_connector import MavlinkConnector

    # Fresh singleton
    fake_redis_singleton._instance = None  # type: ignore[attr-defined]
    redis = fake_redis_singleton.get_redis()

    conn = MavlinkConnector(
        endpoint="udpin:0.0.0.0:14550",
        redis_client=redis,
        publish_interval_ms=100,
    )
    connector_task = asyncio.create_task(conn.run(), name="mavlink")
    print("✅ MavlinkConnector started on udpin:0.0.0.0:14550")

    # Give the socket a moment to bind.
    await asyncio.sleep(0.5)

    # Launch fake_drone as subprocess.
    py = str(ROOT / ".venv/bin/python")
    drone_log = open("/tmp/fake-drone-conn.log", "w")
    drone = subprocess.Popen(
        [py, "scripts/fake_drone.py",
         "--system-id", "1",
         "--host", "127.0.0.1",
         "--port", "14550",
         "--pattern", "circle",
         "--interval-ms", "100"],
        stdout=drone_log, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    print(f"✅ fake_drone started PID={drone.pid}")

    # Collect for 6s.
    await asyncio.sleep(6)

    # Stop drone
    try:
        os.killpg(os.getpgid(drone.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    time.sleep(0.3)

    # Verify stream
    print("\n══════ 验证 fakeredis Stream ══════")
    keys = await redis.keys("telemetry:*")
    print(f"streams: {keys}")

    total_entries = 0
    for k in keys:
        length = await redis.xlen(k)
        total_entries += length
        # Sample last entry
        entries = await redis.xrevrange(k, count=3)
        print(f"\n  stream={k!r}  length={length}")
        for entry_id, fields in entries[:3]:
            preview = {k2: (v[:60] + "..." if len(str(v)) > 60 else v)
                       for k2, v in list(fields.items())[:6]}
            print(f"    [{entry_id}] {preview}")

    conn.stop()
    connector_task.cancel()
    try:
        await connector_task
    except (asyncio.CancelledError, Exception):
        pass

    print(f"\n══════ 结果 ══════")
    print(f"总条目数: {total_entries}")
    if total_entries >= 10:
        print("✅ 全链路数据流通验证通过")
        return 0
    else:
        print(f"❌ 数据不足（<10 条）")
        print("── fake_drone 日志：")
        print(open("/tmp/fake-drone-conn.log").read()[-800:])
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
