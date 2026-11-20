# DJI Cloud API v2 对接层（可测骨架）

## 现状

`backend/app/services/dji_cloud_connector.py` 实现了 DJI Cloud API v2 的**云平台侧**对接骨架：

- `mode="mock"`（默认）：无需硬件/凭证/网络，仿真 1 台 M300 over 南宁，产出 DJI 格式 OSD 遥测，响应航线/直播/返航指令
- `mode="cloud"`：真机模式，走 MQTT，需 `pip install paho-mqtt` + DJI 开发者凭证

**重要边界**：这是对接层骨架，不是完整飞控。它把 DJI 物模型消息映射成 SkyMaster 的遥测槽和指令。

**已接入启动栈**：`app/main.py` 的 `START_TELEMETRY_STACK` 分支会按 `settings.dji_mode` 创建连接器并挂进遥测栈——从数据库读 `protocol="dji"` 且 `metadata.dji_device_sn` 的无人机，自动建立 `SN → Drone UUID` 映射。因此 DJI mock 遥测与 MAVLink 仿真走同一条链路（Redis Stream → consumer → flight_logs + WS 广播 → 前端），**前端无需改动**。演示库已建一台 `DJI-M300-01`（`MOCKM300-01` / gateway `MOCKDOCK001`）。真机对接时按下方步骤切换即可。

## 协议映射（已在代码中实现）

| 能力 | DJI 协议 | SkyMaster 侧 |
|---|---|---|
| 设备拓扑 | `sys/product/{sn}/status` method=`update_topo` | `connector.topology` |
| 遥测 | `thing/product/{sn}/osd` (QoS0) | `parse_osd()` → canonical slot（与 MAVLink 同构） |
| 航线准备 | `thing/product/{sn}/services` method=`flighttask_prepare` | `flighttask_prepare()` |
| 执行/暂停/恢复/取消 | 同上 `flighttask_execute/pause/resume/cancel` | 对应方法 |
| 直播推流 | method=`live_start_push` (RTMP) | `start_live()` → 指向 MediaMTX |
| 返航 | method=`return_home` | `return_home()` |
| **DRC 实时控制** | `thing/product/{sn}/drc` method=`control` (QoS0) | `send_drc()` — 四轴摇杆 [-1,1] 打包成 `drc` 整数 |
| 断线重连 | MQTT CONNACK / on_disconnect | 指数退避 1s→60s + 抖动，连接成功后重置 |
| 消息封装 | `bid/tid/timestamp/method/data/need_reply` | `envelope()` |

## 测试

```bash
cd backend
.venv/bin/python -m pytest tests/test_dji_drc_ack.py tests/test_dji_cloud_connector.py \
  tests/test_dji_calibration.py tests/test_dji_calibration_reply.py \
  tests/test_dji_mission.py tests/test_dji_mission_api.py \
  tests/test_dji_api.py tests/test_dji_calibration_api.py -q
# 83 passed（含 DRC 回执、校准状态机与 reply、飞行任务状态机、RC 死区映射、API 边界校验）
```

## 真机启用步骤（硬件到位后）

1. **开发者准备**
   - 在 DJI 开发者平台注册企业开发者，创建 Cloud API 类型应用
   - 获取 `App ID` / `App Key` / `App License`
   - 机场固件 ≥ V3.8.0、Pilot 2 遥控器固件 ≥ V5.3.0
   - 开放网络：443 (HTTPS) / 1883 或 8883 (MQTT)

2. **安装依赖**
   ```bash
   cd backend && .venv/bin/pip install paho-mqtt
   ```

3. **配置环境变量**（不写死在代码里）
   ```bash
   export DJI_MODE=cloud
   export DJI_GATEWAY_SN=<你的机场SN或遥控器SN>
   export DJI_BROKER_HOST=<DJI提供的MQTT端点>
   export DJI_BROKER_PORT=8883
   export DJI_CLIENT_ID=<工作区分配的client_id>
   export DJI_USERNAME=<MQTT用户名>
   export DJI_PASSWORD=<MQTT密码>
   ```

4. **WPML 航线文件**：`flighttask_prepare()` 当前把 waypoint 列表放在 `data.waypoints`（骨架用）。真机需替换为符合 DJI WPML 规范的 KMZ 文件引用，见 DJI Cloud API 文档「航线管理」。

5. **无人机记录**：真机 SN 写进 Drone 的 `metadata.dji_device_sn`，`protocol="dji"`。启动栈会自动配对，无需改代码。示例：
   ```bash
   curl -X POST localhost:8000/api/v1/drones -H 'Content-Type: application/json' \
     -d '{"sn":"DJI-M30-01","protocol":"dji","metadata":{"dji_device_sn":"<真机SN>","dji_gateway_sn":"<你的机场SN>"}}'
   ```

6. **验证顺序**：拓扑上报 → OSD 遥测入库 → 下发一条准备+执行航线 → 直播推流到 MediaMTX → 返航。

## DRC 实时控制用法

**前端摇杆面板**（`/dashboard/dji-control`，导航"DJI 摇杆"）：双虚拟摇杆——左杆油门/偏航、右杆俯仰/横滚，拖动时每 100ms 下发一次 DRC，松手自动回中；带四轴实时值、后端回显、**指令回执状态**、返航/悬停/直播快捷指令和安全警告。对应后端 API：

| 端点 | 说明 |
|---|---|
| `GET /api/v1/dji/status` | 连接器状态 / 飞机列表 / last_drc / **drc_link（指令回执）** / 状态 / 重连次数 |
| `POST /api/v1/dji/drc` | `{drone_sn, throttle, yaw, pitch, roll}` 四轴 [-1,1] |
| `POST /api/v1/dji/action` | `{action: return_home\|hover\|live_start\|mission, drone_sn, ...}` |

代码直调：

```python
connector.send_drc("MOCKM300-01", throttle=0.5, yaw=0.1, pitch=0.0, roll=-0.2)
# 轴取值 [-1,1]，打包进 drc 整数，QoS0 高频下发
# mock 模式记录在 connector.last_drc[sn]，并置 _mock_state[sn]="DRC"
```

**DRC 回执闭环**：参数在独立文件 `backend/config/dji_control.json`（回执延迟、超时、序列号回绕、应答字段名）。`send_drc()` 为每条指令分配递增 `drc_seq` 并记录 pending；设备在上报 OSD / state / events 时回传序列号，`handle_drc_ack()` 匹配后写入 `last_drc_ack`（含执行轴回显与往返延迟），mock 模式按配置延迟自动回执，cloud 模式超时标记 `timeout`。高频指令只保留最后一次 pending——回执确认的是最新指令。

⚠️ DRC 是真飞控指令，真机模式下 `throttle/pitch/roll` 直接驱动电机——接入真机前务必先在 DJI 模拟器或安全空域验证轴方向与量程映射。回执字段名与固件相关，真机联调时按实际回包核对 `ack_fields`。

## 校准中心（`/dashboard/calibration`，导航「校准中心」）

**参数独立文件**：校准时长、提示文案、九步采集序列、默认死区全部在
`backend/config/dji_calibration.json`；代码不硬编码。摇杆采集结果写入
`backend/data/dji_rc_calibration.json`，可用 `DJI_CALIBRATION_CONFIG` /
`DJI_RC_CALIBRATION_FILE` 环境变量覆盖路径。

传感器校准（指南针 / IMU / 云台 / 视觉定位）：前端 1.5s 轮询状态机，
`mock` 模式按 tick 推进进度至 `success`。

**cloud 模式 reply 自动绑定**：`_on_mqtt_message()` 收到
`thing/product/{sn}/services_reply` 后调用 `_handle_services_reply()`：
- 校准项与飞机 SN 优先取 `data.item` / `data.drone_sn`；设备未回显时通过
  请求记录的 `bid` / `tid` 关联恢复（关联在首次匹配后清除）
- 状态映射：字符串 `running/in_progress/calibrating` → running，
  `done/complete/success` → success，`failed/error` → failed，
  `cancelled` → cancelled；数字按 0=idle / 1=running / 2=success /
  3=failed / 4=cancelled
- `progress` 支持 0..100 与 0..1 两种表示；`result/code` 非 0 直接判 failed
  （失败优先于进度），`message/msg/reason` 写入状态说明

摇杆九点采集：左杆油门/偏航 + 右杆俯仰/横滚，
依次采集 8 个极值与中位，保存每轴 `min/center/max`，`apply_rc_axis()`
按正/负半轴分别缩放并套用死区。

| 端点 | 说明 |
|---|---|
| `GET /api/v1/dji/calibration/status?drone_sn=` | 校准项定义、各机状态机、已保存 RC 参数、完整配置 |
| `POST /api/v1/dji/calibration/start` | `{drone_sn, item}` 启动传感器校准 / 打开 RC 向导 |
| `POST /api/v1/dji/calibration/cancel` | `{drone_sn, item}` 取消进行中的校准 |
| `POST /api/v1/dji/calibration/rc` | `{drone_sn, axes, deadzone?}` 保存九点采集结果 |

代码直调：

```python
connector.start_calibration("MOCKM300-01", "compass")
connector.mock_tick(6)   # 12s 配置 → progress 50%
connector.set_rc_calibration("MOCKM300-01", axes)
connector.apply_rc_axis("MOCKM300-01", "throttle", 0.5)
```

## 飞行任务（`/dashboard/mission`，导航「DJI 任务」）

**参数独立文件**：`backend/config/dji_mission.json`（默认高度、航点上限、状态枚举映射、progress/result/task_id 字段名）与 `backend/config/dji_mission_routes.json`（三条南宁 12309 预设巡逻航线，绕开核心禁飞区并控制在限高 150m 内）。可用 `DJI_MISSION_CONFIG` / `DJI_MISSION_ROUTES` 环境变量覆盖路径。

**状态机**：`prepared → running ↔ paused → success / failed / cancelled`。`create_mission()` 返回 task_id 并记录每机最新任务；`execute / pause / resume / cancel` 用 task_id 或飞机 SN 关联，下发时携带 `drone_sn` 以便多机正确路由。mock 每 tick 推进一个航点并计算百分比，飞完自动 `success`；cloud 解析 `flighttask_progress`：进度兼容 0..100 与 0..1，状态支持字符串/数字枚举，`result/code` 非 0 判失败（失败优先），task_id 缺失时按 SN 回退关联。

| 端点 | 说明 |
|---|---|
| `GET /api/v1/dji/mission/routes` | 预设航线列表 |
| `GET /api/v1/dji/mission/status?drone_sn=&task_id=` | 任务状态机、航线与配置 |
| `POST /api/v1/dji/mission/prepare` | `{drone_sn, route_id? , waypoints?}` 下发任务，返回 task_id |
| `POST /api/v1/dji/mission/control` | `{task_id, action: execute\|pause\|resume\|cancel}` 控制任务 |

前端页面提供航线卡片选择、航点表格、任务进度与操作日志；执行完成后显示「航线执行完成」。旧端点 `POST /dji/action` 的 `mission` 动作保留兼容，内部已改用真实 task_id（不再硬编码 `api-task`）。

## 已知限制

- `mode="cloud"` 尚未做 MQTT TLS/clientAuth 配置（真机 8883 端口需要）
- OSD→canonical 映射覆盖主要字段，云台/负载/告警字段待按需扩展
- 航线仍是 waypoint 列表骨架，非 WPML KMZ；断点续飞未实现（`flighttask_progress` 已用于进度状态回传，不等于断点续飞）
- DRC 已实现指令下发、四轴打包、序列号回执闭环（含延迟/超时状态）与前端摇杆面板；真机回包字段与延迟阈值需按固件联调核对
- 校准项通过 `thing/product/{sn}/services` 的 `calibration` 方法下发；真机方法名/参数需按固件物模型核对。`services_reply` → `update_calibration()` 已自动绑定，但状态枚举按 DJI 常见约定映射，真机联调时需按实际固件回包字段核对
