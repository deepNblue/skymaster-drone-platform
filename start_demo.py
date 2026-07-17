#!/usr/bin/env python3
"""nohup 常驻启动 SkyMaster dev demo 栈供用户浏览器实测。

启动：backend + fake_drone (circle @ 北京) + frontend。
不 kill 已有进程；把 PID 写到 /tmp/skymaster-demo.pids 便于停止。
"""
import os, subprocess, sys, time
from pathlib import Path

BACKEND = Path("/home/duoduo/projects/skymaster-drone-platform/backend-v0.1")
FRONTEND = Path("/home/duoduo/projects/skymaster-drone-platform/frontend-v0.1")
PY = str(BACKEND / ".venv/bin/python")
NODE_BIN = os.path.expanduser("~/.nvm/versions/node/v20.20.1/bin")
os.environ["PATH"] = f"{NODE_BIN}:{os.environ['PATH']}"


def spawn(name, args, cwd, log):
    p = subprocess.Popen(
        args, cwd=str(cwd),
        stdout=open(log, "w"), stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        start_new_session=True,   # detach so it survives this script
    )
    print(f"✅ {name} PID={p.pid}  → {log}")
    return p


def main():
    pids = {}
    pids["backend"] = spawn(
        "backend", [PY, "scripts/dev_stack.py"], BACKEND, "/tmp/demo-backend.log"
    ).pid
    time.sleep(6)

    pids["drone1"] = spawn(
        "drone-beijing",
        [PY, "scripts/fake_drone.py", "--system-id", "1",
         "--port", "14550", "--pattern", "circle", "--interval-ms", "200",
         "--command-http", "15001"],
        BACKEND, "/tmp/demo-drone1.log",
    ).pid
    pids["drone2"] = spawn(
        "drone-chengdu",
        [PY, "scripts/fake_drone.py", "--system-id", "2",
         "--port", "14550", "--pattern", "line",
         "--lat", "30.5728", "--lng", "104.0668", "--interval-ms", "200",
         "--command-http", "15002"],
        BACKEND, "/tmp/demo-drone2.log",
    ).pid
    time.sleep(1)

    pids["frontend"] = spawn(
        "frontend", ["npm", "run", "dev"], FRONTEND, "/tmp/demo-frontend.log"
    ).pid

    # Write pid file
    with open("/tmp/skymaster-demo.pids", "w") as f:
        for k, v in pids.items():
            f.write(f"{k}={v}\n")

    print("\n══════ Demo Stack Live ══════")
    print("  Backend    :  http://localhost:8000/docs")
    print("  Frontend   :  http://localhost:3000  → /dashboard/live")
    print("  Drones     :  sysid=1 (Beijing circle), sysid=2 (Chengdu line)")
    print("  PIDs       :  /tmp/skymaster-demo.pids")
    print("\n  Stop with: while read L; do kill -9 ${L#*=} 2>/dev/null; done < /tmp/skymaster-demo.pids")


if __name__ == "__main__":
    main()
