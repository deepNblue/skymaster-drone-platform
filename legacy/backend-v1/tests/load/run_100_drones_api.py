"""
REST API 压测器 - httpx AsyncClient

场景:
    50 并发用户, 30 秒, 每个用户循环打:
        1. GET /api/devices           (设备列表)
        2. GET /api/devices/{random}   (单设备)
        3. GET /api/devices/{random}/telemetry (最新遥测)
        4. GET /api/statistics         (统计)

指标:
    - 各端点 P50/P95/P99 延迟
    - 总吞吐 QPS
    - 错误率
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    return s[min(int(len(s) * p / 100.0), len(s) - 1)]


class Metrics:
    def __init__(self):
        self.endpoint_latencies: dict = {}
        self.errors = 0
        self.success = 0

    def record(self, ep: str, ms: float, ok: bool):
        if ok:
            self.endpoint_latencies.setdefault(ep, []).append(ms)
            self.success += 1
        else:
            self.errors += 1


async def user_loop(uid: int, base_url: str, stop_evt: asyncio.Event, drone_ids: list, metrics: Metrics):
    """单用户循环打 4 个端点"""
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        while not stop_evt.is_set():
            # 1. /api/devices
            t = time.perf_counter()
            try:
                r = await client.get("/api/devices")
                metrics.record("/api/devices", (time.perf_counter() - t) * 1000, r.status_code == 200)
            except Exception:
                metrics.record("/api/devices", 0, False)

            # 2. /api/devices/{id}
            did = random.choice(drone_ids)
            t = time.perf_counter()
            try:
                r = await client.get(f"/api/devices/{did}")
                metrics.record("/api/devices/{id}", (time.perf_counter() - t) * 1000, r.status_code == 200)
            except Exception:
                metrics.record("/api/devices/{id}", 0, False)

            # 3. /api/devices/{id}/telemetry
            t = time.perf_counter()
            try:
                r = await client.get(f"/api/devices/{did}/telemetry")
                # 遥测端点前 1s 内可能 404 (fleet 还没发第一波), 视为正常
                ok = r.status_code in (200, 404)
                metrics.record("/api/devices/{id}/telemetry", (time.perf_counter() - t) * 1000, ok)
            except Exception:
                metrics.record("/api/devices/{id}/telemetry", 0, False)

            # 4. /api/statistics
            t = time.perf_counter()
            try:
                r = await client.get("/api/statistics")
                metrics.record("/api/statistics", (time.perf_counter() - t) * 1000, r.status_code == 200)
            except Exception:
                metrics.record("/api/statistics", 0, False)

            await asyncio.sleep(0.05)  # 20 req 4-tuple/s per user


async def main(args):
    base_url = f"http://127.0.0.1:{args.port}"
    print("=" * 70)
    print(f"REST API 压测 · {args.users} 用户 · {args.duration}s · target={base_url}")
    print("=" * 70)

    # 等待服务端 warmup (fleet 至少发一轮遥测, 避免 telemetry 端点大面积 404)
    await asyncio.sleep(1.5)

    drone_ids = [f"drone-{i:03d}" for i in range(args.total_drones)]
    metrics = Metrics()
    stop_evt = asyncio.Event()

    users = [
        asyncio.create_task(user_loop(i, base_url, stop_evt, drone_ids, metrics))
        for i in range(args.users)
    ]

    t0 = time.time()
    await asyncio.sleep(args.duration)
    stop_evt.set()
    await asyncio.sleep(1.0)
    for u in users:
        u.cancel()
    elapsed = time.time() - t0

    # 输出
    print()
    print("=" * 70)
    print("REST API 压测结果")
    print("=" * 70)
    print(f"运行时长        : {elapsed:.2f}s")
    print(f"成功请求        : {metrics.success}")
    print(f"失败请求        : {metrics.errors}")
    print(f"总吞吐 QPS      : {metrics.success / elapsed:.1f}")
    print(f"错误率          : {metrics.errors / max(1, metrics.success + metrics.errors) * 100:.2f}%")
    print()

    print("--- 各端点延迟 (ms) ---")
    print(f"{'端点':<40}{'样本':>8}{'P50':>10}{'P95':>10}{'P99':>10}")
    for ep, lats in metrics.endpoint_latencies.items():
        p50 = percentile(lats, 50)
        p95 = percentile(lats, 95)
        p99 = percentile(lats, 99)
        print(f"{ep:<40}{len(lats):>8}{p50:>10.2f}{p95:>10.2f}{p99:>10.2f}")

    # SLA 判定: 所有端点 P95 < 200ms, 错误率 < 1%
    print()
    print("=" * 70)
    print("SLA 判定")
    print("=" * 70)
    sla_pass = True
    for ep, lats in metrics.endpoint_latencies.items():
        p95 = percentile(lats, 95)
        result = "✅" if p95 < args.sla_p95_ms else "❌"
        print(f"{result} {ep:<40} P95 = {p95:.2f} ms  (阈值 {args.sla_p95_ms}ms)")
        if p95 >= args.sla_p95_ms:
            sla_pass = False

    err_rate = metrics.errors / max(1, metrics.success + metrics.errors) * 100
    err_ok = err_rate < 1.0
    print(f"{'✅' if err_ok else '❌'} 错误率 < 1%          {err_rate:.2f}%")
    if not err_ok:
        sla_pass = False

    print()
    print(f"总体            : {'✅ REST API 100 机 SLA 达标' if sla_pass else '❌ SLA 未达标'}")
    return 0 if sla_pass else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--total-drones", type=int, default=100)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--sla-p95-ms", type=float, default=200.0)
    args = ap.parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)
