# DJI Cloud API v2 对接层（可测骨架）

## 现状

`backend/app/services/dji_cloud_connector.py` 实现了 DJI Cloud API v2 的**云平台侧**对接骨架：

- `mode="mock"`（默认）：无需硬件/凭证/网络，仿真 1 台 M300 over 南宁，产出 DJI 格式 OSD 遥测，响应航线/直播/返航指令
- `mode="cloud"`：真机模式，走 MQTT，需 `pip install paho-mqtt` + DJI 开发者凭证

**重要边界**：这是对接层骨架，不是完整飞控。它把 DJI 物模型消息映射成 SkyMaster 的遥测槽和指令，尚未接入 `app/main.py` 的自动启动栈（当前 telemetry stack 仍只跑 MAVLink）。真机对接时按下方步骤启用。

## 协议映射（已在代码中实现）

| 能力 | DJI 协议 | SkyMaster 侧 |
|---|---|---|
| 设备拓扑 | `sys/product/{sn}/status` method=`update_topo` | `connector.topology` |
| 遥测 | `thing/product/{sn}/osd` (QoS0) | `parse_osd()` → canonical slot（与 MAVLink 同构） |
| 航线准备 | `thing/product/{sn}/services` method=`flighttask_prepare` | `flighttask_prepare()` |
| 执行/暂停/恢复/取消 | 同上 `flighttask_execute/pause/resume/cancel` | 对应方法 |
| 直播推流 | method=`live_start_push` (RTMP) | `start_live()` → 指向 MediaMTX |
| 返航 | method=`return_home` | `return_home()` |
| 消息封装 | `bid/tid/timestamp/method/data/need_reply` | `envelope()` |

## 测试

```bash
cd backend
.venv/bin/python -m pytest tests/test_dji_cloud_connector.py -q
# 15 passed
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

5. **接入自动启动栈**：在 `app/main.py` 的 telemetry stack 初始化处，按 `settings.dji_mode` 分支创建 `DJICloudConnector` 并加入 `_connectors`/tasks（与 MavlinkConnector 并列）。

6. **验证顺序**：拓扑上报 → OSD 遥测入库 → 下发一条准备+执行航线 → 直播推流到 MediaMTX → 返航。

## 已知限制

- `mode="cloud"` 尚未做 MQTT TLS/clientAuth 配置、指数退避重连（协议文档建议 1s→30s + 抖动）
- OSD→canonical 映射覆盖主要字段，云台/负载/告警字段待按需扩展
- 航线是 waypoint 列表骨架，非 WPML KMZ；断点续飞 (`flighttask_progress`) 未实现
- DRC 实时飞行控制（`thing/product/{sn}/drc/*`）未实现
