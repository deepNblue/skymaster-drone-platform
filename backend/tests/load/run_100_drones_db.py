"""
100 机遥测入库压测 (场景 D)

场景:
    100 台无人机 x 1Hz 遥测, 批量入库 SQLite (WAL 模式),
    模拟真实生产入库 I/O 压力.
    对比测试三种入库策略:
        1. 单条 INSERT (基线, 最差)
        2. 批量 executemany (推荐)
        3. 批量 + WAL + prepared statement

指标:
    - 入库延迟 P50/P95/P99
    - 每秒入库行数 (rows/s)
    - 数据库文件大小增长
    - SLA: 单批入库 P95 < 100 ms

依赖: 仅标准库 sqlite3 + psutil
"""

import argparse
import asyncio
import os
import statistics
import sys
import sqlite3
import time
from pathlib import Path

import psutil

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))

from backend.tests.load.mock_drone import MockFleet, WebSocketManager


DB_PATH = "/tmp/skymaster_load_test.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    latitude REAL,
    longitude REAL,
    altitude REAL,
    roll REAL,
    pitch REAL,
    yaw REAL,
    battery_voltage REAL,
    battery_remaining INTEGER,
    gps_fix_type INTEGER,
    satellites INTEGER
);
CREATE INDEX IF NOT EXISTS idx_telem_device_ts ON telemetry(device_id, timestamp DESC);
"""


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    return s[min(int(len(s) * p / 100.0), len(s) - 1)]


def setup_db(mode: str) -> sqlite3.Connection:
    """初始化 SQLite 连接"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
    if mode in ("wal", "batch_wal"):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


class TelemetryBuffer:
    """遥测数据缓冲区, 定时批量落盘"""

    def __init__(self, conn: sqlite3.Connection, batch_size: int = 100, mode: str = "batch"):
        self.conn = conn
        self.batch_size = batch_size
        self.mode = mode
        self.buffer: list = []
        self.batch_latencies: list = []
        self.total_rows = 0

    def add(self, device_id: str, telem):
        row = (
            device_id, telem.timestamp,
            telem.latitude, telem.longitude, telem.altitude,
            telem.roll, telem.pitch, telem.yaw,
            telem.battery_voltage, telem.battery_remaining,
            telem.gps_fix_type, telem.satellites,
        )
        if self.mode == "single":
            # 单条 INSERT (基线)
            t = time.perf_counter()
            self.conn.execute(
                "INSERT INTO telemetry(device_id,timestamp,latitude,longitude,altitude,"
                "roll,pitch,yaw,battery_voltage,battery_remaining,gps_fix_type,satellites) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
            self.batch_latencies.append((time.perf_counter() - t) * 1000)
            self.total_rows += 1
        else:
            self.buffer.append(row)
            if len(self.buffer) >= self.batch_size:
                self.flush()

    def flush(self):
        if not self.buffer:
            return
        t = time.perf_counter()
        self.conn.executemany(
            "INSERT INTO telemetry(device_id,timestamp,latitude,longitude,altitude,"
            "roll,pitch,yaw,battery_voltage,battery_remaining,gps_fix_type,satellites) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            self.buffer,
        )
        self.batch_latencies.append((time.perf_counter() - t) * 1000)
        self.total_rows += len(self.buffer)
        self.buffer.clear()


async def run_scenario(mode: str, args) -> dict:
    """跑一次场景, 返回指标字典"""
    print()
    print(f"▶️  跑场景: mode={mode}")

    ws = WebSocketManager()
    fleet = MockFleet(size=args.drones, ws_manager=ws, rate_hz=args.rate)
    conn = setup_db(mode)

    batch_size = 1 if mode == "single" else args.batch_size
    buffer = TelemetryBuffer(conn, batch_size=batch_size, mode=mode)

    # Hook: 每次 send_telemetry 时也入库
    orig_send = ws.send_telemetry

    async def hooked(device_id, telem):
        buffer.add(device_id, telem)
        await orig_send(device_id, telem)

    ws.send_telemetry = hooked

    # 采样 CPU/mem
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)
    cpu_samples, mem_samples = [], []

    async def sample_sys():
        end = asyncio.get_event_loop().time() + args.duration
        while asyncio.get_event_loop().time() < end:
            cpu_samples.append(proc.cpu_percent(None))
            mem_samples.append(proc.memory_info().rss / 1024 / 1024)
            await asyncio.sleep(1.0)

    t0 = time.time()
    await asyncio.gather(fleet.run(args.duration), sample_sys())
    # 最后 flush 一波
    buffer.flush()
    elapsed = time.time() - t0

    # DB 大小
    db_size_mb = os.path.getsize(DB_PATH) / 1024 / 1024

    # 行数验证
    cur = conn.execute("SELECT COUNT(*) FROM telemetry")
    row_count = cur.fetchone()[0]
    conn.close()

    return {
        "mode": mode,
        "elapsed": elapsed,
        "rows_written": buffer.total_rows,
        "rows_in_db": row_count,
        "rows_per_sec": buffer.total_rows / elapsed,
        "batch_p50_ms": percentile(buffer.batch_latencies, 50),
        "batch_p95_ms": percentile(buffer.batch_latencies, 95),
        "batch_p99_ms": percentile(buffer.batch_latencies, 99),
        "batch_max_ms": max(buffer.batch_latencies) if buffer.batch_latencies else 0,
        "batches": len(buffer.batch_latencies),
        "cpu_max": max(cpu_samples) if cpu_samples else 0,
        "cpu_avg": statistics.mean(cpu_samples) if cpu_samples else 0,
        "mem_max_mb": max(mem_samples) if mem_samples else 0,
        "db_size_mb": db_size_mb,
    }


async def main(args):
    print("=" * 70)
    print(f"SkyMaster 100 机遥测入库压测 · 场景 D · 持续 {args.duration}s")
    print(f"参数: drones={args.drones}, rate={args.rate}Hz, batch_size={args.batch_size}")
    print("=" * 70)

    modes = ["single", "batch", "batch_wal"] if not args.mode else [args.mode]
    results = []
    for m in modes:
        r = await run_scenario(m, args)
        results.append(r)

    # 报告
    print()
    print("=" * 70)
    print("入库压测结果")
    print("=" * 70)
    print(f"{'策略':<12}{'行数':>8}{'吞吐(行/s)':>14}{'批P50':>10}{'批P95':>10}{'批P99':>10}{'DB(MB)':>10}{'CPU峰':>8}")
    for r in results:
        print(f"{r['mode']:<12}"
              f"{r['rows_written']:>8}"
              f"{r['rows_per_sec']:>14.1f}"
              f"{r['batch_p50_ms']:>10.3f}"
              f"{r['batch_p95_ms']:>10.3f}"
              f"{r['batch_p99_ms']:>10.3f}"
              f"{r['db_size_mb']:>10.2f}"
              f"{r['cpu_max']:>7.1f}%")

    # SLA 判定 (以推荐策略 batch_wal 为准)
    print()
    print("=" * 70)
    print("SLA 判定 (推荐策略: batch_wal)")
    print("=" * 70)
    target = next((r for r in results if r["mode"] == "batch_wal"), results[0])

    sla_pass = True
    p95 = target["batch_p95_ms"]
    result = "✅" if p95 < args.sla_p95_ms else "❌"
    print(f"{result} 单批入库 P95 < {args.sla_p95_ms}ms   : {p95:.3f} ms")
    if p95 >= args.sla_p95_ms:
        sla_pass = False

    expected_rows = args.drones * args.rate * args.duration
    completeness = target["rows_written"] / expected_rows * 100
    result = "✅" if completeness >= 95 else "❌"
    print(f"{result} 数据完整率 >= 95%          : {completeness:.1f}%  ({target['rows_written']}/{expected_rows:.0f})")
    if completeness < 95:
        sla_pass = False

    cpu_ok = target["cpu_max"] < 80
    result = "✅" if cpu_ok else "❌"
    print(f"{result} CPU 峰值 < 80%              : {target['cpu_max']:.1f}%")
    if not cpu_ok:
        sla_pass = False

    print()
    print(f"总体              : {'✅ 100 机入库 SLA 达标' if sla_pass else '❌ SLA 未达标'}")

    # 清理
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    return 0 if sla_pass else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drones", type=int, default=100)
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--mode", choices=["single", "batch", "batch_wal"], default=None,
                    help="不指定则跑三种策略对比")
    ap.add_argument("--sla-p95-ms", type=float, default=100.0)
    args = ap.parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)
