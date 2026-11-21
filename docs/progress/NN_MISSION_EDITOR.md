# SkyMaster v0.1 · NN 里程碑 — Mission Editor 端到端

## ✅ 新增能力：地图上点点画航线，一键派发

用户在 CesiumMap 上左键点击 → 自动累积成航点列表 → 右侧面板显示 → 点「派发」→ 无人机自主飞行。

```
[Cesium 地图左键]
    │
    ▼   ScreenSpaceEventHandler → pick(ray) → cartographic
onMapClick(lat, lng)
    │
    ▼   waypoints.push({lat, lng, alt: defaultAlt})
MissionEditorPanel 列表 + 地图上 CYAN 航线+编号点
    │
    ▼   POST /api/v1/sim/drones/{sysid}/mission
Backend Sim Router 代理
    │
    ▼
FakeDrone HTTP → state.mode = "mission"
    │
    ▼   _pattern_mission() 逐点飞行 @ 20 m/s
MAVLink UDP → WS 更新地图上的实时位置
```

## 📊 NN 端到端实测

```
📍 模拟点击 4 航点
   #1  (39.9050, 116.4080) @80m
   #2  (39.9100, 116.4140) @100m
   #3  (39.9150, 116.4200) @120m
   #4  (39.9200, 116.4260) @100m

初始位置        : (39.9042, 116.4074)
POST mission    : {'ok': True, 'mode': 'mission'}
8s 后位置       : (39.9057, 116.4088)
状态            : mode=mission, mission_progress=1/4

✅ Mission Editor 端到端 OK — 无人机已开始飞第 1 段
```

## 🧩 新增/改动

| 文件 | 变更 |
|---|---|
| `components/CesiumMap.tsx` | 新增 `onMapClick(lat, lng)`、`followPrimary` props；用 `ScreenSpaceEventHandler` 转换屏幕点 → 大地坐标；忽略实体点击避免误触；unmount 清理 handler |
| `components/MissionEditorPanel.tsx` | **新增** — 右侧悬浮面板：开始/停止绘制、默认高度、航点列表（可单独改高度/删除）、派发按钮、清空 |
| `app/dashboard/live/page.tsx` | 挂载 MissionEditorPanel；把点击事件转成 waypoints；waypoints 回传给 CesiumMap 作为可视化图层 |

## 🎮 演示流程

1. 打开 `http://localhost:3000/dashboard/live`
2. 右上角「✏️ 任务编辑器」面板
3. 点「开始绘制」→ 按钮变红「停止绘制」
4. 在地图上任意点击 3~5 次 → 每次生成 CYAN 编号点 + 连线
5. 单独调航点高度（默认 100m，可改）
6. 点「派发 (N)」→ 无人机进入 mission 模式，状态徽章实时 1/N → 2/N → …
7. 完成后再点「清空」重来

## 📈 累计成果（LL + MM + NN）

| 阶段 | 能力 |
|---|---|
| LL | 前端看到多机实时遥测（3D 地球 + CYAN 圆点移动） |
| MM | 按钮控制：GOTO / RTL / 悬停 / 派发预制任务 |
| **NN** | **地图上画任务：点击 → 派发 → 无人机执行** |

Backend 46 pass / 1 skipped · Frontend tsc 0 error · 全链路演示级 demo ✅

## ⚠️ 遗留

- [ ] followPrimary 相机跟随（已实现 props，未接入 UI）
- [ ] 3D 无人机模型（当前是圆点）
- [ ] postgres:16 + TelemetryConsumer 落库
- [ ] mission 完成通知（可加 WS event 让面板自动清空）

🐈
