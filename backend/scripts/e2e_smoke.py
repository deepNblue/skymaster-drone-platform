#!/usr/bin/env python3
"""Full pipeline smoke — spawns dev_stack + fake_drone, verifies WS receives telemetry."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import websockets

ROOT = Path("/home/duoduo/projects/skymaster-drone-platform/backend-v0.1")
PY = str(ROOT / ".venv/bin/python")


async def wait_ready(port=8000, timeout=20):
    import urllib.error
    import urllib.request
    for i in range(timeout):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2)
            if r.status == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def main():
    stack = subprocess.Popen(
        [PY, "scripts/dev_stack.py"], cwd=str(ROOT),
        stdout=open("/tmp/e2e-stack.log", "w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        preexec_fn=os.setsid,
    )
    print(f"✅ dev_stack PID={stack.pid}")

    ready = await wait_ready()
    if not ready:
        print("❌ backend not ready")
        print(open("/tmp/e2e-stack.log").read()[-1500:])
        os.killpg(os.getpgid(stack.pid), signal.SIGTERM)
        return 1
    print("✅ backend ready")
    await asyncio.sleep(1.5)  # let MAVLink socket bind

    drone = subprocess.Popen(
        [PY, "scripts/fake_drone.py",
         "--system-id", "1", "--port", "14550",
         "--pattern", "circle", "--interval-ms", "100"],
        cwd=str(ROOT),
        stdout=open("/tmp/e2e-drone.log", "w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        preexec_fn=os.setsid,
    )
    print(f"✅ fake_drone PID={drone.pid}")
    await asyncio.sleep(2)

    print("\n── WS 订阅 ──")
    msgs = []
    try:
        async with websockets.connect(
            "ws://127.0.0.1:8000/api/v1/ws/telemetry/1",
            open_timeout=5, close_timeout=2,
        ) as ws:
            end = asyncio.get_event_loop().time() + 6
            while len(msgs) < 8 and asyncio.get_event_loop().time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    try:
                        msgs.append(json.loads(raw))
                    except Exception:
                        msgs.append({"raw": str(raw)[:100]})
                except asyncio.TimeoutError:
                    continue
    except Exception as e:
        print(f"  WS error: {e}")

    print(f"\n✅ 收到 {len(msgs)} 条 WS 消息")
    for i, m in enumerate(msgs[:3]):
        s = json.dumps(m, ensure_ascii=False, default=str)
        print(f"  [{i}] {s[:180]}")

    print("\n── dev_stack log 关键行 ──")
    log = open("/tmp/e2e-stack.log").read()
    for line in log.splitlines()[-15:]:
        print(f"  {line}")

    # Cleanup
    for p in (drone, stack):
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            time.sleep(0.3)
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass

    return 0 if len(msgs) >= 3 else 2


if __name__ == "__main__":
    code = asyncio.run(main())
    print(f"\n=== exit {code} ===")
    sys.exit(code)
