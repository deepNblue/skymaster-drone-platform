# SkyMaster 压测目录

## 场景 A · 应用层压测（快速）

**冒烟**：
```bash
cd backend
pip install psutil
python3 -m backend.tests.load.run_100_drones --duration 10
```

**正式（60s + SLA 判定）**：
```bash
python3 -m backend.tests.load.run_100_drones --duration 60 --sla-p95-ms 500
```

## 场景 B · 真 WebSocket 网络栈压测

**终端 1** — 启动 uvicorn + FastAPI 服务器（内置 100 台无人机）：
```bash
python3 -m backend.tests.load.ws_server --drones 100 --duration 90 --port 8765
```

**终端 2** — 跑客户端压测：
```bash
python3 -m backend.tests.load.run_100_drones_ws --duration 30 --port 8765
```

## 场景 C · REST API 压测

**终端 1** — 启动 API 服务器（REST + WS 复合端点）：
```bash
python3 -m backend.tests.load.api_server --drones 100 --duration 90 --port 8766
```

**终端 2** — 跑 REST 压测（50 并发用户 × 4 端点）：
```bash
python3 -m backend.tests.load.run_100_drones_api --duration 30 --users 50 --port 8766
```

## 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--drones` | 100 | 无人机数量 |
| `--clients` | 30 | 前端订阅者数量 |
| `--subs-per-client` | 3 | 每客户端订阅无人机数 |
| `--rate` | 1.0 | 遥测频率 Hz |
| `--duration` | 60.0 | 持续时长 秒 |
| `--sla-p95-ms` | 500 | SLA 阈值 |

## 输出指标

- 遥测吞吐 (msg/s)
- 端到端延迟 P50/P95/P99 (ms)
- CPU/内存占用
- 内存漂移检测 (>50MB 视为泄漏)
- asyncio 事件循环 lag
- SLA 达标判定（exit code 0/1）

## 文件

- `mock_drone.py` — 模拟无人机遥测数据源（含内联 WebSocketManager）
- `mock_client.py` — 模拟前端 WebSocket 订阅者（in-process）
- `run_100_drones.py` — 场景 A 一键入口
- `ws_server.py` — 场景 B FastAPI 服务器（真 WS 网络栈）
- `run_100_drones_ws.py` — 场景 B 客户端压测器

## 实测结果（2026-07-16）

- **场景 A 应用层**：P95 = 0.54 ms（富余 926×）
- **场景 B 真 WS 网络栈**：P95 = 4.98 ms（富余 100×）
- **场景 C REST API**：4 端点 P95 全部 < 36 ms（富余 5.6-11.6×），错误率 0%
- ✅ 100 机 SLA 严重富余

完整报告见 `docs/CAPACITY_100_DRONES.md`

