"""
100 无人机压测入口脚本

场景:
    - 100 台 MockDrone 各按 1Hz 生成遥测
    - 30 个 MockClient 前端订阅者, 每人订阅 3 架无人机 (共 90 次订阅)
    - 持续 60 秒 (可通过 --duration 调整)

指标:
    - 遥测吞吐: 消息/秒
    - 端到端延迟: P50 / P95 / P99 (ms)
    - CPU / 内存占用 (psutil)
    - asyncio 事件循环延迟 (loop lag)

运行:
    cd backend
    python3 -m tests.load.run_100_drones --duration 60
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from pathlib import Path

# 允许直接 python3 tests/load/run_100_drones.py 也可跑
# api/v1/safety.py 使用 `from ...core.safety`, 需要把项目根 (backend 的父目录) 加入 sys.path
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent.parent          # …/backend
_PROJECT_ROOT = _BACKEND.parent          # …/skymaster-drone-platform
sys.path.insert(0, str(_PROJECT_ROOT))

import psutil  # 依赖: pip install psutil

from backend.tests.load.mock_drone import MockFleet
from backend.tests.load.mock_client import MockClient


class LoopLagMonitor:
    """测量 asyncio 事件循环延迟

    原理: 定时 sleep(interval), 期望恢复时间是 interval, 实际差值即为 lag
    """

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.lags_ms: list[float] = []
        self._running = False

    async def run(self, duration: float):
        self._running = True
        end = asyncio.get_event_loop().time() + duration
        while self._running and asyncio.get_event_loop().time() < end:
            expected = asyncio.get_event_loop().time() + self.interval
            await asyncio.sleep(self.interval)
            actual = asyncio.get_event_loop().time()
            lag = (actual - expected) * 1000.0  # ms
            self.lags_ms.append(max(0.0, lag))

    def stop(self):
        self._running = False


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = int(len(s) * p / 100.0)
    k = min(k, len(s) - 1)
    return s[k]


async def main(args):
    print("=" * 70)
    print(f"SkyMaster 100 机压测 · 持续 {args.duration}s · rate={args.rate}Hz")
    print("=" * 70)

    from backend.tests.load.mock_drone import WebSocketManager
    ws_manager = WebSocketManager()

    # 1. 创建 100 台无人机
    fleet = MockFleet(size=args.drones, ws_manager=ws_manager, rate_hz=args.rate)
    print(f"[创建] {args.drones} 台 MockDrone")

    # 2. 创建 30 个前端客户端, 每个订阅 3 架无人机
    clients: list[MockClient] = []
    for i in range(args.clients):
        subs = random.sample([d.drone_id for d in fleet.drones], args.subs_per_client)
        c = MockClient(f"client-{i:02d}", subs, ws_manager)
        await c.connect()
        clients.append(c)
    print(f"[连接] {args.clients} 个 MockClient (每人订阅 {args.subs_per_client} 架)")
    print(f"[订阅总数] {args.clients * args.subs_per_client}")

    # 3. 启动 loop-lag 监控
    lag_mon = LoopLagMonitor(interval=0.1)

    # 4. 启动系统资源采样
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)  # 预热
    cpu_samples: list[float] = []
    mem_samples: list[float] = []

    async def sample_sys():
        end = asyncio.get_event_loop().time() + args.duration
        while asyncio.get_event_loop().time() < end:
            cpu_samples.append(proc.cpu_percent(None))
            mem_samples.append(proc.memory_info().rss / 1024 / 1024)  # MB
            await asyncio.sleep(1.0)

    # 5. 并发启动: 编队 + 客户端 + 监控
    t_start = time.time()
    await asyncio.gather(
        fleet.run(args.duration),
        lag_mon.run(args.duration),
        sample_sys(),
    )
    elapsed = time.time() - t_start

    # 6. 收集指标
    total_sent = fleet.total_sent()
    total_received = sum(c.received_count for c in clients)
    all_latencies: list[float] = []
    for c in clients:
        all_latencies.extend(c.latencies_ms)

    # 7. 输出报告
    print()
    print("=" * 70)
    print("压测报告")
    print("=" * 70)
    print(f"实际运行时长        : {elapsed:.2f}s")
    print(f"无人机发送消息总数  : {total_sent}")
    print(f"客户端接收消息总数  : {total_received}")
    print(f"预期消息数          : {args.drones * args.rate * args.duration * args.subs_per_client * args.clients // args.drones}")
    print(f"吞吐 (msg/s)        : {total_received / elapsed:.1f}")
    print()
    print("--- 端到端延迟 (ms) ---")
    if all_latencies:
        print(f"样本数              : {len(all_latencies)}")
        print(f"平均                : {statistics.mean(all_latencies):.2f}")
        print(f"P50                 : {percentile(all_latencies, 50):.2f}")
        print(f"P95                 : {percentile(all_latencies, 95):.2f}")
        print(f"P99                 : {percentile(all_latencies, 99):.2f}")
        print(f"最大                : {max(all_latencies):.2f}")
    print()
    print("--- 系统资源 ---")
    if cpu_samples:
        print(f"CPU 平均            : {statistics.mean(cpu_samples):.1f}%")
        print(f"CPU 峰值            : {max(cpu_samples):.1f}%")
    if mem_samples:
        print(f"内存平均            : {statistics.mean(mem_samples):.1f} MB")
        print(f"内存峰值            : {max(mem_samples):.1f} MB")
        # 内存泄漏检测: 末尾 20% 平均 vs 起始 20% 平均
        n = len(mem_samples)
        if n >= 10:
            head = statistics.mean(mem_samples[: n // 5])
            tail = statistics.mean(mem_samples[-n // 5 :])
            drift = tail - head
            print(f"内存漂移            : {drift:+.1f} MB ({'⚠️ 疑似泄漏' if drift > 50 else '✅ 无泄漏'})")
    print()
    print("--- Asyncio 事件循环 ---")
    if lag_mon.lags_ms:
        print(f"Loop Lag 平均       : {statistics.mean(lag_mon.lags_ms):.2f} ms")
        print(f"Loop Lag P95        : {percentile(lag_mon.lags_ms, 95):.2f} ms")
        print(f"Loop Lag 峰值       : {max(lag_mon.lags_ms):.2f} ms")

    # 8. SLA 判定
    print()
    print("=" * 70)
    print("SLA 判定")
    print("=" * 70)
    sla_pass = True
    if all_latencies:
        p95 = percentile(all_latencies, 95)
        result = "✅ PASS" if p95 < args.sla_p95_ms else "❌ FAIL"
        print(f"遥测 P95 < {args.sla_p95_ms}ms       : {p95:.2f}ms  {result}")
        if p95 >= args.sla_p95_ms:
            sla_pass = False
    if cpu_samples:
        cpu_max = max(cpu_samples)
        result = "✅ PASS" if cpu_max < 80 else "❌ FAIL"
        print(f"CPU 峰值 < 80%          : {cpu_max:.1f}%  {result}")
        if cpu_max >= 80:
            sla_pass = False
    print()
    print(f"总体结果            : {'✅ 100 机 SLA 达标' if sla_pass else '❌ SLA 未达标'}")
    return 0 if sla_pass else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drones", type=int, default=100)
    ap.add_argument("--clients", type=int, default=30)
    ap.add_argument("--subs-per-client", type=int, default=3)
    ap.add_argument("--rate", type=float, default=1.0, help="遥测频率 Hz")
    ap.add_argument("--duration", type=float, default=60.0, help="持续时长 秒")
    ap.add_argument("--sla-p95-ms", type=float, default=500.0)
    args = ap.parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)
