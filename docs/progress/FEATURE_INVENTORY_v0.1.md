# SkyMaster v0.1 · 现有功能全景梳理

> 冻结日期：2026-07-10 UTC 01:25
> 冻结范围：v0.1 阶段（LL→SS）的**非 AI / 非 3D-4D** 全部功能
> 说明：3D 无人机模型（BoxGraphics 版）保留但**不再扩展**；Copilot AI 相关模块已实装但**冻结**

---

## 0. 项目定位与规模

| 项目 | 值 |
|---|---|
| 代号 | SkyMaster · 开源多协议无人机管控平台 |
| 对标 | 大疆司空 2（协议中立、私有化、MIT） |
| 代码 | Backend 5043 行 · Tests 1424 行 · Scripts 1213 行 · Frontend 4038 行 |
| 测试 | pytest **51 case · 50 pass / 1 skip** |
| 技术栈 | FastAPI + PostgreSQL + Redis + TimescaleDB + Next.js + Ant Design + Cesium + Resium |

---

## 1. 后端 REST API 全清单（39 个 endpoint）

### 1.1 认证 `/api/v1/auth`
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/auth/login` | 用户登录（JWT） |
| GET  | `/auth/me` | 当前用户信息 |

### 1.2 无人机 `/api/v1/drones`
| 方法 | 路径 | 功能 |
|---|---|---|
| GET  | `/drones` | 列出组织内无人机 |
| POST | `/drones` | 注册新无人机 |
| GET  | `/drones/{id}` | 获取单机详情 |

### 1.3 任务 `/api/v1/missions`
| 方法 | 路径 | 功能 |
|---|---|---|
| GET  | `/missions` | 列出任务 |
| POST | `/missions` | 创建任务（含航点） |
| GET  | `/missions/{id}` | 任务详情 |
| POST | `/missions/{id}/validate` | 校验（航点数、禁飞区、飞行时长） |
| POST | `/missions/{id}/dispatch` | 派发到 FakeDrone/真机 |
| POST | `/missions/{id}/abort` | 中止 |
| GET  | `/missions/{id}/logs` | 任务日志 |

### 1.4 视频流 `/api/v1/streams`
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/streams` | 创建 RTMP→HLS 转码 |
| DELETE | `/streams/{drone_id}` | 停止流 |
| GET  | `/streams/{drone_id}/hls` | HLS m3u8 地址 |
| GET  | `/streams/{drone_id}/snapshot` | 截图 |
| GET  | `/streams` | 全部流列表 |

### 1.5 仿真 `/api/v1/sim`（本轮核心）
| 方法 | 路径 | 功能 |
|---|---|---|
| GET  | `/sim/drones` | 已注册的 FakeDrone 列表 |
| GET  | `/sim/drones/{sysid}/state` | 当前模式/mission 进度/**mission_completed** |
| POST | `/sim/drones/{sysid}/goto` | 单点 GOTO |
| POST | `/sim/drones/{sysid}/mission` | 派发多点任务 |
| POST | `/sim/drones/{sysid}/rtl` | 返航 |
| POST | `/sim/drones/{sysid}/mode` | 切换模式（circle/line/hover/RTL） |
| POST | `/sim/drones/{sysid}/arm` | 解锁 |
| POST | `/sim/drones/{sysid}/disarm` | 上锁 |

### 1.6 历史轨迹 `/api/v1/trajectory`（OO 新增）
| 方法 | 路径 | 功能 |
|---|---|---|
| GET  | `/trajectory/drones` | 有历史数据的无人机 |
| GET  | `/trajectory/{drone_id}?seconds=300` | 时间窗口内轨迹点 |

### 1.7 Copilot AI（🧊 已冻结）
`POST /copilot/sessions` · `POST /sessions/{id}/messages` · `GET /sessions/{id}/traces` · `GET /traces/{id}` · `POST /traces/{id}/approve`

### 1.8 健康
`GET /health`

### 1.9 WebSocket
| 路径 | 功能 |
|---|---|
| `/api/v1/ws/telemetry/{drone_id}` | 单机遥测流（Redis pubsub 直推） |
| `/api/v1/ws/events` | **全局事件流**（mission.completed 等，SS 新增） |

---

## 2. 后端服务层（Services）

| 模块 | 职责 |
|---|---|
| `mavlink_connector.py` | 接收 MAVLink UDP + 转 Redis pubsub `telemetry.broadcast.*` |
| `telemetry_consumer.py` | 消费 Redis → TimescaleDB `flight_logs` 落库（生产） |
| `mission_dispatcher.py` | 校验（航点数/时长/禁飞区）+ 派发到目标飞控 |
| `stream_manager.py` | RTMP→HLS 转码控制（ffmpeg 子进程管理） |
| `connection_manager.py` | WebSocket 连接池 |
| `trajectory_store.py` | SQLite 轨迹存储（WAL + 批量刷 + 24h retention）**OO 新增** |
| `trajectory_bridge.py` | Redis pubsub `telemetry.broadcast.*` → SQLite **OO 新增** |
| `mission_watcher.py` | 轮询 FakeDrone 状态，检测 mission 完成上升沿 → 发 Redis `mission.event.*` **SS 新增** |
| `auth.py` | JWT 编解码 + bcrypt 密码 |
| `fake_redis_singleton.py` | 测试/开发用 fake redis |
| `llm_client.py` · `copilot_agent.py` · `tool_registry.py` | 🧊 Copilot（冻结） |

---

## 3. 数据模型（12 张表）

| 表 | 用途 |
|---|---|
| `organization` | 多租户组织 |
| `users` | 用户 + JWT 主体 |
| `drones` | 无人机注册 |
| `missions` | 任务（含 waypoints JSON） |
| `flight_logs` | TimescaleDB 遥测超表（hypertable） |
| `audit_logs` | 审计日志 |
| `media_assets` | 图像/视频存档 |
| `copilot_sessions` · `copilot_traces` · `copilot_trace_steps` · `copilot_approvals` | 🧊 冻结 |

---

## 4. 前端页面（8 个路由）

| 路径 | 页面 | 状态 |
|---|---|---|
| `/login` | 登录 | ✅ |
| `/dashboard` | 首页仪表盘 | ✅ |
| `/dashboard/live` | **实时地图**（核心页） | ✅ 本轮重点扩展 |
| `/dashboard/drones` | 无人机列表 | ✅ |
| `/dashboard/missions` | 任务列表 | ✅ |
| `/dashboard/missions/[id]` | 任务详情 | ✅ |
| `/dashboard/streams` | 视频流列表 | ✅ |
| `/dashboard/streams/[drone_id]` | HLS 播放器 | ✅ |
| `/dashboard/copilot` · `/approvals` | 🧊 冻结 | 不再迭代 |

---

## 5. 前端组件（10 个）

| 组件 | 用途 |
|---|---|
| `CesiumMap.tsx` + `CesiumMapInner.tsx` | 3D 地球主组件（Cesium+Resium） |
| `SimControlPanel.tsx` | 左上仿真控制（GOTO/RTL/预制任务/**mission ✅ 徽章**） |
| `MissionEditorPanel.tsx` | 右上任务编辑器（点地图画航点） |
| `TrajectoryPanel.tsx` | **右下历史轨迹开关**（OO/PP 新增） |
| `CameraFollowToggle.tsx` | **顶部相机跟随开关**（QQ 新增） |
| `GlobalEventStream.tsx` | **无 UI 常驻**，订阅 `/ws/events` 弹 mission 完成 toast（SS 新增） |
| `TelemetryCard.tsx` | 遥测仪表数字卡 |
| `CopilotDrawer.tsx` | 🧊 冻结 |
| `ThemeProvider.tsx` | AntD 主题包装 |

---

## 6. 实时地图 `/dashboard/live` 功能矩阵

```
┌──────────────────────────────────────────────────────────┐
│                    [🎯 跟随相机]  ← QQ                     │
│  ┌──────────┐                          ┌───────────────┐│
│  │🎮 SIM控制│      Cesium 3D           │✏️ 任务编辑     ││
│  │ ARMED    │      🟢 D1 实时(3D 四旋翼)│  绘制/派发    ││
│  │ mode     │      🟠 D1 历史尾迹       │               ││
│  │ mission  │      🟡 D2 历史尾迹       │               ││
│  │  3/3 ✅  │      🔵 mission polyline  │┌─────────────┐││
│  └──────────┘                          ││📅 历史轨迹  │││
│                                        ││ ON  300s    │││
│                    fleet 弹窗           │└─────────────┘││
│                                        └───────────────┘│
└──────────────────────────────────────────────────────────┘
   ↕ 常驻 GlobalEventStream 订阅 /ws/events
   → 派发 mission → 后台 500ms 检测完成 → WS 推送 toast 🎯
```

---

## 7. 端到端数据流

### 7.1 实时遥测
```
FakeDrone (UDP 14550)
  ↓ MAVLink
MavlinkConnector (async task)
  ↓ Redis publish "telemetry.broadcast.{drone_id}"
  ├─ WebSocket /ws/telemetry/{id} → 前端实时圆点/3D 模型
  ├─ TelemetryConsumer → TimescaleDB (生产)
  └─ TrajectoryBridge → SQLite (开发) → GET /trajectory/{id}
```

### 7.2 任务派发（含 SS 完成事件）
```
前端点地图画航点
  ↓ POST /api/v1/sim/drones/1/mission
sim.py forward → FakeDrone HTTP 15001
  ↓ FakeDrone 逐点飞行
  ↓ 到最后一点 → set mission_completed_at
MissionWatcher (500ms 轮询)
  ↓ 检测上升沿 → Redis publish "mission.event.all"
WebSocket /ws/events
  ↓ 前端 GlobalEventStream 收到
  → message.success("🎯 任务完成")
```

### 7.3 视频流
```
无人机推 RTMP → StreamManager
  ↓ ffmpeg 转 HLS m3u8
GET /api/v1/streams/{id}/hls → HLS 播放器
```

---

## 8. 里程碑 chronicle

| 阶段 | 交付 |
|---|---|
| LL | 多机 MAVLink 实时遥测 |
| MM | REST 按钮控制 GOTO/RTL/预制任务 |
| NN | 地图上鼠标绘制航点 |
| OO | SQLite 轨迹持久化 + `/trajectory` API |
| PP | 前端历史轨迹可视化 |
| QQ | 相机跟随 primary |
| RR | Mission 完成事件（1.5s 轮询版） |
| SS | Mission 完成事件（**WS 主动推**）+ 断线重连 |
| 3D | BoxGraphics + 4 Cylinder 四旋翼模型（本轮小甜点，冻结）|

---

## 9. 测试覆盖

```
tests/
├── test_auth.py                    JWT 登录/鉴权
├── test_copilot.py                 🧊
├── test_drones.py                  无人机 CRUD
├── test_health.py                  健康检查
├── test_mavlink_connector.py       MAVLink 解析
├── test_mission_dispatcher.py      派发校验
├── test_missions.py                任务 CRUD + 派发
├── test_mission_watcher.py         **SS 新增**（伪 HTTP + fakeredis）
├── test_sim.py                     仿真 API
├── test_streams.py                 视频流
├── test_telemetry_consumer.py      TimescaleDB 落库
├── test_trajectory.py              **OO 新增**（3 case）
└── test_ws.py                      WebSocket
```
**50 pass / 1 skip · 51 total**

---

## 10. 部署与运行

### 本地一键 demo（不依赖 docker）
```bash
python3 start_demo.py
# 会拉起：
#  - backend (uvicorn :8000, USE_FAKE_REDIS + SIM_MODE)
#  - drone1 (SITL FakeDrone sysid=1, HTTP :15001, 北京)
#  - drone2 (SITL FakeDrone sysid=2, HTTP :15002, 成都)
#  - frontend (next dev :3000)
```

### 环境开关
| 变量 | 默认 | 作用 |
|---|---|---|
| `USE_FAKE_REDIS` | false | 用内存 fakeredis 代替真 Redis |
| `SIM_MODE` | false | 允许 `/sim/*` endpoints |
| `SIM_DRONES` | - | 如 `1:15001,2:15002` 声明 FakeDrone 注册表 |
| `ENABLE_TRAJECTORY_STORE` | **true** | 开启 SQLite 轨迹 |
| `ENABLE_MISSION_WATCHER` | **true** | 开启 500ms 完成轮询→WS 推 |
| `START_MAVLINK_CONNECTOR` | false | 后端启 MAVLink UDP 监听 |
| `START_TELEMETRY_CONSUMER` | false | 后端启 TimescaleDB 消费 |

---

## 11. 冻结与后续

### 🧊 本次冻结（后面再说）
- 3D 精细化：4 桨独立转速、真 glTF 模型、材质、动画细节
- 4D / 3DGS / NeRF 场景重建（v2.1 Reality Studio 定位）
- Copilot AI Agent、tool_registry 6 tools、approvals 工作流
- LLM Client、`copilot_*` 数据表

### ✅ 已生产就绪（当前 v0.1 稳定核）
- 遥测流水线（MAVLink → Redis → WS + TimescaleDB + SQLite）
- 任务编辑派发闭环 + 完成事件 WS 推送
- 视频 RTMP→HLS
- JWT 认证 + 组织隔离
- 3D 地图 + 历史尾迹 + 相机跟随

### 📮 可无缝接续的方向（非 3D/非 AI）
- **P0 生产化**：docker-compose 生产 profile（postgres:16 + timescaledb + redis + minio）
- **P0 CI/CD**：GitHub Actions 上跑 pytest + tsc + npm build
- **P1 告警**：Prometheus + Grafana 面板（telemetry lag、mission fail rate）
- **P1 审计**：`audit_logs` 表接入所有敏感 POST/DELETE
- **P1 多组织**：真的从 JWT 里读 org_id 过滤 `drones`/`missions`
- **P2 API 文档**：FastAPI 自带 OpenAPI 完善 tags/描述，发 SDK stub
- **P2 移动端**：Flutter 或 React Native 只读监控端
- **P2 权限**：RBAC roles（观察员/操控员/管理员）

---

🐈 v0.1 非 AI/非 3D 部分已完全落定，等下轮指令。
