# Sprint 1 · MAVLink 真实接入

**目标**：backend 能接入 PX4 SITL，收到心跳/遥测，落库，WS 广播，能上传航点

## 6 步骤计划（U1 混合模式）

| # | 子任务 | 目标产出 | 估时 |
|---|---|---|---|
| 1 | MAVLink Connector 主进程 | `app/services/mavlink_connector.py` 独立可跑 · UDP 14550 收心跳 · 打印遥测 | 60-120s |
| 2 | Redis Streams 发布 | Connector 把遥测发到 `telemetry:{drone_id}` stream · 含 lat/lng/alt/battery | 60-120s |
| 3 | TelemetryService 消费+落库 | 独立 worker 消费 Redis · batch insert flight_logs (TimescaleDB) | 60-180s |
| 4 | WebSocket 广播 | `/ws/telemetry/{drone_id}` 真实推送 · 从 Redis Stream 订阅 | 60-120s |
| 5 | Mission Upload 实现 | `POST /missions/{id}/dispatch` → pymavlink WP upload → 状态回写 | 120-240s |
| 6 | docker-compose 补 PX4 SITL | 加 `px4-sitl` 服务 · 集成测试脚本 | 60-120s |

**累计预算**：~10-15 分钟
