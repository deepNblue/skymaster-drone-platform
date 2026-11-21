"""
SSE Fanout Compressor - 场景 E · v2.x SSE 通路压测

背景:
    v1.x (backend/api/v1/main.py) 通过 WebSocketManager 做 fan-out.
    v2.x (backend-v0.1) 走 SSE (Server-Sent Events):
      - Scene progress stream: scenes.py L402
      - Copilot response stream: copilot.py L162
    但 v2.x 目前是"每 request 独立 poll DB"的实现,
    100 客户端同时订阅 = 100 个数据库连接持续 poll, 存在放大隐患.

本压测:
    模拟 SSE fanout 广播器 (in-proc, 无网络栈), 测量:
      - N 个源 (drone_id / scene_id) 各自定时更新
      - M 个订阅端同时订阅 subset
      - 消息端到端延迟 (源发出 → 订阅端收到)

指标:
    - fanout 延迟 P50/P95/P99
    - 消息完整率
    - 内存占用 (broadcaster 队列)

用途:
    为 v2.1 SSE 通路优化 (从 poll-based 迁移到 pub/sub) 提供 baseline.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import psutil


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    return s[min(int(len(s) * p / 100.0), len(s) - 1)]


@dataclass
class Event:
    source_id: str
    seq: int
    sent_ts: float
    payload: dict


class SSEBroadcaster:
    """
    SSE 广播器 mock.
    - 每个 source_id 有独立的 asyncio.Queue
    - 每个 subscriber 订阅一个或多个 source_id
    - publish() 把事件 push 到对应订阅者的 queue
    """

    def __init__(self):
        # source_id -> set[Queue]
        self.subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.total_delivered = 0

    def subscribe(self, source_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subscribers[source_id].add(q)
        return q

    def unsubscribe(self, source_id: str, q: asyncio.Queue) -> None:
        self.subscribers[source_id].discard(q)

    async def publish(self, source_id: str, event: Event) -> None:
        """
        非阻塞广播: 满队列直接丢 (模拟慢客户端).
        并发 fan-out 用 gather 拉平.
        """
        subs = list(self.subscribers.get(source_id, set()))
        if not subs:
            return

        async def _put(q: asyncio.Queue):
            try:
                q.put_nowait(event)
                self.total_delivered += 1
            except asyncio.QueueFull:
                pass

        await asyncio.gather(*[_put(q) for q in subs])


class Source:
    """事件源 (模拟一台无人机 / 一个 scene job)"""

    def __init__(self, source_id: str, broadcaster: SSEBroadcaster, rate_hz: float):
        self.source_id = source_id
        self.broadcaster = broadcaster
        self.interval = 1.0 / rate_hz
        self.seq = 0
        self._stop = False

    def stop(self):
        self._stop = True

    async def run(self, duration: float):
        end = asyncio.get_event_loop().time() + duration
        while not self._stop and asyncio.get_event_loop().time() < end:
            ev = Event(
                source_id=self.source_id,
                seq=self.seq,
                sent_ts=time.perf_counter(),
                payload={"status": "progress", "pct": self.seq % 100},
            )
            await self.broadcaster.publish(self.source_id, ev)
            self.seq += 1
            await asyncio.sleep(self.interval)


class Subscriber:
    """订阅端 (模拟前端 EventSource)"""

    def __init__(self, sub_id: int, source_ids: list, broadcaster: SSEBroadcaster):
        self.sub_id = sub_id
        self.source_ids = source_ids
        self.broadcaster = broadcaster
        self.queues: list[asyncio.Queue] = []
        self.latencies: list[float] = []
        self.received = 0

    def subscribe_all(self):
        for sid in self.source_ids:
            q = self.broadcaster.subscribe(sid)
            self.queues.append(q)

    async def consume(self, duration: float):
        """
        并行消费所有订阅的 queue.
        每个 queue 一个协程, 收到消息记录延迟.
        """
        end = asyncio.get_event_loop().time() + duration + 5  # +5s 收尾

        async def _drain(q: asyncio.Queue):
            while asyncio.get_event_loop().time() < end:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                lat = (time.perf_counter() - ev.sent_ts) * 1000
                self.latencies.append(lat)
                self.received += 1

        await asyncio.gather(*[_drain(q) for q in self.queues])


async def main(args):
    print("=" * 70)
    print(f"SSE Fanout 压测 · 场景 E · v2.x SSE 通路")
    print(f"参数: sources={args.sources}, subs={args.subs}, "
          f"per_sub={args.sources_per_sub}, rate={args.rate}Hz, "
          f"duration={args.duration}s")
    print("=" * 70)

    br = SSEBroadcaster()

    # 创建源
    sources = [Source(f"src-{i:03d}", br, args.rate) for i in range(args.sources)]

    # 每个订阅端订阅 N 个源 (确定性哈希分配)
    import random
    random.seed(42)
    subs = []
    for i in range(args.subs):
        assigned = random.sample(range(args.sources), args.sources_per_sub)
        source_ids = [f"src-{j:03d}" for j in assigned]
        s = Subscriber(i, source_ids, br)
        s.subscribe_all()
        subs.append(s)

    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)
    mem_baseline = proc.memory_info().rss / 1024 / 1024
    cpu_samples = []
    mem_samples = []

    async def sample_sys():
        end = asyncio.get_event_loop().time() + args.duration
        while asyncio.get_event_loop().time() < end:
            cpu_samples.append(proc.cpu_percent(None))
            mem_samples.append(proc.memory_info().rss / 1024 / 1024)
            await asyncio.sleep(1.0)

    t0 = time.time()
    await asyncio.gather(
        *[s.run(args.duration) for s in sources],
        *[s.consume(args.duration) for s in subs],
        sample_sys(),
    )
    elapsed = time.time() - t0

    # 汇总
    all_lats = []
    for s in subs:
        all_lats.extend(s.latencies)

    total_expected_per_sub = args.duration * args.rate * args.sources_per_sub
    total_received = sum(s.received for s in subs)
    completeness = total_received / (total_expected_per_sub * args.subs) * 100

    print()
    print("=" * 70)
    print("SSE Fanout 压测结果")
    print("=" * 70)
    print(f"运行时长       : {elapsed:.2f}s")
    print(f"总投递次数     : {br.total_delivered}")
    print(f"订阅端接收总数 : {total_received}")
    print(f"消息完整率     : {completeness:.1f}%")
    print()
    print("--- fanout 延迟 (ms) ---")
    if all_lats:
        print(f"样本量  : {len(all_lats)}")
        print(f"P50     : {percentile(all_lats, 50):.3f} ms")
        print(f"P95     : {percentile(all_lats, 95):.3f} ms")
        print(f"P99     : {percentile(all_lats, 99):.3f} ms")
        print(f"最大    : {max(all_lats):.3f} ms")
    print()
    print("--- 资源占用 ---")
    print(f"CPU 峰值 : {max(cpu_samples) if cpu_samples else 0:.1f}%")
    print(f"CPU 均值 : {statistics.mean(cpu_samples) if cpu_samples else 0:.1f}%")
    print(f"内存基线 : {mem_baseline:.1f} MB")
    print(f"内存峰值 : {max(mem_samples) if mem_samples else 0:.1f} MB")
    print(f"内存漂移 : +{(max(mem_samples) - mem_baseline) if mem_samples else 0:.1f} MB")

    # SLA 判定
    print()
    print("=" * 70)
    print("SLA 判定")
    print("=" * 70)
    sla_pass = True

    p95 = percentile(all_lats, 95)
    result = "✅" if p95 < args.sla_p95_ms else "❌"
    print(f"{result} fanout 延迟 P95 < {args.sla_p95_ms}ms : {p95:.3f} ms")
    if p95 >= args.sla_p95_ms:
        sla_pass = False

    completeness_ok = completeness >= 95
    result = "✅" if completeness_ok else "❌"
    print(f"{result} 消息完整率 >= 95%           : {completeness:.1f}%")
    if not completeness_ok:
        sla_pass = False

    cpu_max = max(cpu_samples) if cpu_samples else 0
    cpu_ok = cpu_max < 80
    result = "✅" if cpu_ok else "❌"
    print(f"{result} CPU 峰值 < 80%              : {cpu_max:.1f}%")
    if not cpu_ok:
        sla_pass = False

    print()
    print(f"总体             : {'✅ SSE Fanout SLA 达标' if sla_pass else '❌ SLA 未达标'}")
    return 0 if sla_pass else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=int, default=100,
                    help="事件源数量 (相当于 drones 或 scene jobs)")
    ap.add_argument("--subs", type=int, default=30,
                    help="订阅端数量 (相当于前端 EventSource)")
    ap.add_argument("--sources-per-sub", type=int, default=10,
                    help="每订阅端订阅多少个源")
    ap.add_argument("--rate", type=float, default=1.0, help="源发送频率 Hz")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--sla-p95-ms", type=float, default=100.0,
                    help="fanout 延迟 P95 阈值 (SSE 通路目标 100ms)")
    args = ap.parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)
