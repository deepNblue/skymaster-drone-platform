"""Spawn N FakeDrone subprocesses, one per (port, region).

    python scripts/fake_drone_swarm.py --count 3 --base-port 14550

Each drone gets a distinct system_id (1..N), UDP port (base..base+N-1),
and start location cycled from a small list of Chinese city centers. Ctrl+C
propagates SIGTERM to every child.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("fake_drone_swarm")


@dataclass(frozen=True)
class _Region:
    name: str
    lat: float
    lng: float


# Distinct start coords so operators can eyeball on a map without overlap.
_REGIONS: List[_Region] = [
    _Region("Beijing",  39.9042, 116.4074),
    _Region("Chengdu",  30.5728, 104.0668),
    _Region("Shenzhen", 22.5431, 114.0579),
    _Region("Shanghai", 31.2304, 121.4737),
    _Region("Xian",     34.3416, 108.9398),
]


def _drone_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_drone.py")


def _spawn_one(i: int, base_port: int, args: argparse.Namespace) -> subprocess.Popen:
    region = _REGIONS[i % len(_REGIONS)]
    port = base_port + i
    sysid = i + 1
    cmd = [
        sys.executable, _drone_script_path(),
        "--system-id", str(sysid),
        "--host", args.host,
        "--port", str(port),
        "--pattern", args.pattern,
        "--lat", str(region.lat),
        "--lng", str(region.lng),
        "--alt", str(args.alt),
        "--interval-ms", str(args.interval_ms),
    ]
    logger.info(
        "spawn drone sysid=%d region=%s endpoint=udpout:%s:%d",
        sysid, region.name, args.host, port,
    )
    # Preserve stdio so operators see per-drone logs; use its own process
    # group so SIGINT to us doesn't reach the child twice on some shells.
    proc = subprocess.Popen(cmd)  # noqa: S603 — args controlled
    print(
        f"[swarm] pid={proc.pid} sysid={sysid} region={region.name} "
        f"endpoint=udpout:{args.host}:{port}"
    )
    return proc


def _terminate(procs: List[subprocess.Popen], sig: int = signal.SIGTERM) -> None:
    for p in procs:
        if p.poll() is None:
            try:
                p.send_signal(sig)
            except ProcessLookupError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Spawn a fleet of FakeDrones")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--base-port", type=int, default=14550)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--pattern", default="circle")
    parser.add_argument("--alt", type=float, default=100.0)
    parser.add_argument("--interval-ms", type=int, default=100)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    procs: List[subprocess.Popen] = []
    stop = {"flag": False}

    def _handler(signum, frame):  # noqa: ARG001
        stop["flag"] = True
        logger.info("Swarm received signal %s; stopping %d drones", signum, len(procs))
        _terminate(procs)

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, _handler)

    try:
        for i in range(args.count):
            procs.append(_spawn_one(i, args.base_port, args))
        logger.info("Swarm ready: %d drones", len(procs))

        # Wait until either everyone exits, or we get Ctrl+C.
        while not stop["flag"]:
            alive = [p for p in procs if p.poll() is None]
            if not alive:
                break
            time.sleep(0.5)
    finally:
        _terminate(procs)
        # Give children a moment; then SIGKILL stragglers.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.1)
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except ProcessLookupError:
                    pass
        for p in procs:
            try:
                p.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        logger.info("Swarm shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
