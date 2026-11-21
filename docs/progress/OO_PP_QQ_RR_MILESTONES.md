# SkyMaster v0.1 · OO + PP + QQ + RR 联合里程碑

## ✅ 一次交付 4 个里程碑
- **OO**：SQLite 轨迹持久化 + Trajectory REST API
- **PP**：前端历史轨迹可视化 + 时间窗口调整
- **QQ**：相机跟随（followPrimary）
- **RR**：Mission 完成事件 + 前端 toast + 徽章 ✅

---

## OO · 轨迹持久化

### 后端
| 文件 | 用途 |
|---|---|
| `app/services/trajectory_store.py` | SQLite backed `TrajectoryStore`；WAL+批量刷盘（500ms 或 200 行）；24h 保留策略 |
| `app/services/trajectory_bridge.py` | Redis `telemetry.broadcast.*` psubscribe → 转发到 store |
| `app/api/v1/trajectory.py` | `GET /trajectory/drones` + `GET /trajectory/{id}?seconds=300` |
| `app/main.py` | lifespan 挂载 store + bridge (env `ENABLE_TRAJECTORY_STORE=true`) |

### 实测
```
tracked drones     : ["1", "2"]
drone 1: 29 points, span 99m   ← 已捕获 circle pattern
drone 2: 19 points, span 30m
```

### 测试
`tests/test_trajectory.py` · 3 case · roundtrip + bad frames + guard 全通过

---

## PP · 历史轨迹前端可视化

### 新增组件
`components/TrajectoryPanel.tsx`
- 右下角悬浮开关（ON/OFF）
- 时间窗口 30~3600 秒可调
- 每 3s 拉取一次；把每架无人机的 trail 传给 CesiumMap
- 每架无人机独立分色（橙/黄/品红/春绿/热粉）

### CesiumMap 扩展
- 新 prop `trails: Trail[]`
- 使用 `PolylineGraphics` + 分色调色板渲染每架无人机的历史线
- 与实时圆点+当前 mission 折线三层叠加

---

## QQ · 相机跟随

### 新增组件
`components/CameraFollowToggle.tsx`
- 顶部中央小按钮（未开启：暗底/开启后：主题色）
- 点击切换 `followPrimary` 布尔值

### CesiumMap 已实现
之前 NN 里已埋好 `useEffect([followPrimary, drone.lat, drone.lng])`  → 每次遥测更新触发 `flyTo`，跟着无人机走。

---

## RR · Mission 完成事件

### FakeDrone 补丁 (`scripts/fake_drone.py`)
- `_pattern_mission()` 每次进入"mission_idx >= len(wps)"分支时置 `_mission_completed_notified=True` + 记录时间戳
- `do_GET("/state")` 返回新增字段：`mission_completed: bool` + `mission_completed_at: float | null`
- `do_POST("/command")` 收到新 mission 时重置这两个字段

### 前端 (`components/SimControlPanel.tsx`)
- 每 1.5s 拉状态时检测 `mission_completed_at` 上升沿
- 首次感知即 `message.success("✅ 无人机 X 任务完成 (N/N)")`
- 徽章从紫色 `mission N/N` 切换为绿色 `mission N/N ✅`

### 实测
```
dispatch → mode=mission
t=3.0s ✅ COMPLETED: mission_progress=1/1, mission_completed=True
```

---

## 📊 联合验证结果

```
══════ OO: Trajectory persistence ══════
  tracked drones: {"drones":["1","2"]}
  drone 1: 29 points, span 99m
  drone 2: 19 points, span 30m

══════ PP + QQ: Frontend hosts new panels ══════
  live page: 6727B  status=200

══════ RR: mission completion event ══════
  dispatch → mode=mission
  t=3.0s ✅ COMPLETED

══════ tests ══════
  Backend: 49 passed / 1 skipped
  Frontend: tsc 0 error
```

---

## 🎮 前端布局最终形态

```
┌───────────────────────────────────────────────────────────┐
│                    [🎯 跟随相机]                            │  ← QQ toggle
│  ┌──────────┐                            ┌──────────────┐│
│  │🎮 仿真控制│      Cesium 3D 地球         │✏️ 任务编辑器 ││
│  │ sysid=1  │                            │ 待派发 3 点  ││
│  │ ARMED    │      🟢 D1 (实时位置)       │ 派发 / 清空  ││
│  │ mission  │      🟠 D1 历史轨迹         │              ││
│  │  3/3 ✅  │      🟡 D2 历史轨迹         │              ││
│  └──────────┘      🔵 mission polyline    │              ││
│                                          │┌────────────┐││
│  ┌──────────┐                            ││📅 历史轨迹 │││
│  │ 无人机弹窗│                            ││ ON  300s   │││
│  └──────────┘  📍 2 台在线 · ✏️ 3 航点     ││ 1:29 2:19 │││
│                                          │└────────────┘││
│                                          └──────────────┘│
└───────────────────────────────────────────────────────────┘
```

---

## 📈 累计能力（LL → RR）

| 阶段 | 能力 |
|------|------|
| LL   | 多机实时遥测 |
| MM   | 按钮控制 GOTO/RTL/预制任务 |
| NN   | 地图上画任务 |
| **OO** | **SQLite 轨迹持久化 + REST API** |
| **PP** | **历史轨迹可视化** |
| **QQ** | **相机跟随** |
| **RR** | **Mission 完成事件通知** |

---

## ⚠️ 遗留

- [ ] 3D 无人机模型（真的 glTF，而不是圆点）
- [ ] postgres:16 + TimescaleDB 生产落库（当前仅 SQLite 开发用）
- [ ] WebSocket 主动推送 mission event（当前是 1.5s 轮询）
- [ ] 轨迹叠加"实时逐帧生长"动画（当前 3s 一批刷新）

🐈
