"""
真 WebSocket 网络压测 - 30 客户端 x 3 订阅

场景:
    与本机 ws_server 建立 30 条真 TCP+WebSocket 连接,
    每条订阅 3 架无人机, 采集端到端延迟指标.

前置:
    另一个终端启动 ws_server:
        python3 -m backend.tests.load.ws_server --drones 100 --duration 120 --port 8765

运行:
    python3 -m backend.tests.load.run_100_drones_ws --duration 60
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import websockets

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = min(int(len(s) * p / 100.0), len(s) - 1)
    return s[k]


async def client_worker(cid: int, url: str, drone_ids: list[str], stop_evt: asyncio.Event, latencies: list[float]):
    """单客户端: 连接 -> 订阅 -> 收消息 -> 记延迟"""
    try:
        async with websockets.connect(url) as ws:
            # 订阅
            for did in drone_ids:
                await ws.send(json.dumps({"type": "subscribe_telemetry", "device_id": did}))
            # 收消息
            while not stop_evt.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "telemetry":
                    now = time.time()
                    ts = msg.get("data", {}).get("timestamp")
                    if ts:
                        latencies.append((now - ts) * 1000.0)
    except Exception as e:
        print(f"[client-{cid}] error: {e}")


async def main(args):
    url = f"ws://127.0.0.1:{args.port}/ws"
    print("=" * 70)
    print(f"真 WebSocket 压测 · {args.clients} 客户端 x {args.subs_per_client} 订阅 · {args.duration}s")
    print(f"目标: {url}")
    print("=" * 70)

    stop_evt = asyncio.Event()
    latencies: list[float] = []

    # 每个客户端订阅一段连续 drone_id
    import random
    random.seed(42)
    all_drone_ids = [f"drone-{i:03d}" for i in range(args.total_drones)]
    tasks = []
    for cid in range(args.clients):
        subs = random.sample(all_drone_ids, args.subs_per_client)
        tasks.append(asyncio.create_task(client_worker(cid, url, subs, stop_evt, latencies)))

    # 等待建连
    await asyncio.sleep(2)

    t0 = time.time()
    await asyncio.sleep(args.duration)
    stop_evt.set()
    await asyncio.sleep(1.5)
    for t in tasks:
        t.cancel()
    elapsed = time.time() - t0

    # 输出
    print()
    print("=" * 70)
    print("真 WS 压测结果")
    print("=" * 70)
    print(f"运行时长        : {elapsed:.2f}s")
    print(f"接收总数        : {len(latencies)}")
    print(f"预期总数        : {args.clients * args.subs_per_client * args.duration * 1.0:.0f}")
    if latencies:
        print(f"吞吐            : {len(latencies) / elapsed:.1f} msg/s")
        print()
        print("--- 端到端延迟 (ms) [含 TCP+WS 网络栈] ---")
        print(f"平均            : {statistics.mean(latencies):.2f}")
        print(f"P50             : {percentile(latencies, 50):.2f}")
        print(f"P95             : {percentile(latencies, 95):.2f}")
        print(f"P99             : {percentile(latencies, 99):.2f}")
        print(f"最大            : {max(latencies):.2f}")

    print()
    print("=" * 70)
    print("SLA 判定")
    print("=" * 70)
    sla_pass = True
    if latencies:
        p95 = percentile(latencies, 95)
        result = "✅ PASS" if p95 < args.sla_p95_ms else "❌ FAIL"
        print(f"遥测 P95 < {args.sla_p95_ms}ms  : {p95:.2f}ms  {result}")
        if p95 >= args.sla_p95_ms:
            sla_pass = False
    else:
        print("❌ FAIL: 无有效延迟样本")
        sla_pass = False

    print()
    print(f"总体           : {'✅ 真 WS 100 机 SLA 达标' if sla_pass else '❌ SLA 未达标'}")
    return 0 if sla_pass else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--clients", type=int, default=30)
    ap.add_argument("--subs-per-client", type=int, default=3)
    ap.add_argument("--total-drones", type=int, default=100)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--sla-p95-ms", type=float, default=500.0)
    args = ap.parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)
