# PX4 SITL / MAVLink 双向链路联调

把 MAVLink 从「单向遥测 + HTTP 命令旁路」升级为**真正的双向 MAVLink v2 链路**：
遥测入、命令出、`COMMAND_ACK` 回执、mission 上传握手全部走真实报文。协议层与真 PX4 一致，
将来接真机只需换 endpoint，不改 connector 代码。

## 为什么不是真 PX4 二进制

本机环境：pymavlink 2.4.42 已装，但没有 PX4 二进制、WSL 未启用 Docker 集成，
`backend/docker-compose.sitl.yml`（`jonasvautherin/px4-gazebo-headless`）当前跑不起来。
因此先用 pymavlink 写一个**协议等价的双向 SITL 模拟器**跑通全链路；`docker-compose.sitl.yml`
保留为真 PX4 阶段的接入点。

## 两条仿真栈（互不干扰）

| 栈 | 启动 | 命令通道 | 用途 |
|---|---|---|---|
| `wsl_stack.sh` | fake_drone_swarm ×3 | 遥测 UDP + **HTTP 旁路** (15001-15003) | 3 机 12309/DJI 演示 |
| `wsl_sitl.sh` | sitl_mavlink_sim ×1 | **双向 MAVLink v2** (默认 14550) | 飞控联调 / ACK / mission 握手 |

两者默认端口都是 14550 —— **不要同时跑**。用 `SITL_PORT=14560 bash wsl_sitl.sh` 避开主栈。

## 关键坑：MAVLINK20=1

pymavlink 只有设 `MAVLINK20=1` 才加载 v20 dialect。否则 `command_ack_send()` 会退化成 v10
签名（没有 `target_system` / `progress` 字段），真机联调时表现为「命令发出去但收不到 ACK / 字段缺失」。
模拟器在 import 阶段强制设置该变量；后端进程与测试脚本也必须带 `MAVLINK20=1`。

## 配置驱动

全部参数在 `backend/config/mavlink_sitl.json`（可用 `MAVLINK_SITL_CONFIG` 覆盖）：

| 配置块 | 作用 |
|---|---|
| `dialect` | dialect 名、`wire_protocol`、`require_mavlink20_env` 自检 |
| `connector` | endpoint / publish 环境变量名、recv 超时、重连退避、stream maxlen、命令 ACK 超时、mission 上传参数 |
| `telemetry` | 心跳/SYS_STATUS/GPS/位置周期、stream 字段集与哨兵值 |
| `sitl` | sysid/component、home 坐标、机型、运动参数、命令码表（arm/set_mode/takeoff/rtl/mission_start）、state HTTP 探针端口 |
| `api` | SIM_DRONES 注册表、HTTP 命令超时 |

代码零硬编码；新增机型/命令/超时只改 JSON。

## 新增能力

### 后端

- `MavlinkConnector.send_command_with_ack(target_system, command, params, timeout_s)`
  — 发 `COMMAND_LONG` 并阻塞等匹配 `COMMAND_ACK`，返回 `{ok, command, result, raw}`。
- `MavlinkConnector.handle_message()` 新增 `COMMAND_ACK` / `MISSION_ACK` 分支，
  记录到 `connector.acks`（返回 `None`，不改变遥测解析契约）。
- 配置驱动的 recv 超时 / 重连退避 / stream maxlen / target_component / confirmation。

### 模拟器脚本

`backend/scripts/sitl_mavlink_sim.py`：

- 单个 `udpout` socket 双向：发 HEARTBEAT / GLOBAL_POSITION_INT / VFR_HUD / ATTITUDE /
  SYS_STATUS / GPS_RAW_INT，同时在同 socket 上 `recv_match` 收命令。
- `COMMAND_LONG` → 改内部状态并回 `COMMAND_ACK(ACCEPTED)`。
- mission 握手：`MISSION_COUNT` → 逐条 `MISSION_REQUEST_INT` → `MISSION_ITEM_INT` →
  `MISSION_ACK(ACCEPTED)`；`MISSION_START` 切 `mission` 模式。
- 可选 `--state-http-port` 暴露 `/state` JSON 探针，测试用它断言「状态真变了」，杜绝 HTTP 旁路假象。

## 快速验证

```bash
# 一键自检（进程级真实 UDP，约 4 秒）
cd ~/projects/skymaster-drone-platform
bash wsl_sitl.sh --check

# 或手动起双向栈
SITL_PORT=14560 bash wsl_sitl.sh
curl -s http://127.0.0.1:15901/state | jq .
```

自检覆盖 3 项：

1. `test_real_telemetry_and_command_ack_roundtrip` — HEARTBEAT / GLOBAL_POSITION_INT 解码入槽，
   ARM 命令收到 ACK(result=0)，state 探针确认命令真被处理。
2. `test_real_mission_upload_handshake` — 完整 mission 上传握手，2 个航点落库、模式切 `mission`。
3. `test_config_and_dialect_guard` — 配置加载与 `MAVLINK20=1` 声明自检。

## 切真 PX4

1. 启用 WSL Docker 集成，修 `backend/.env`（当前缺失），固定 `docker-compose.sitl.yml` 镜像 tag。
2. 用 `udpin:0.0.0.0:14550` 接 PX4 的 `udpout`，或按机场景改 `Drone.meta.mavlink_endpoint`。
3. 按真机物模型核对 `sitl.commands` 命令码与 `custom_mode` 枚举，只改 JSON。
4. 重跑 `bash wsl_sitl.sh --check`（协议层无需改动）。

## 已知限制

- 本轮只做了**协议等价模拟器**，不是真 PX4 飞行动力学；真机固件字段差异仍需核对。
- `send_command_with_ack` 是阻塞式（在 executor 里跑更合适），高并发命令场景需要 ACK 相关性队列。
- `MISSION_ITEM_INT` 的 `mission_type` 参数模拟器固定 0，真 PX4 多 mission 场景需扩展。
- 主栈 `sim.py` 仍走 HTTP 旁路（为 3 机演示保留），本轮未改其命令通道。
