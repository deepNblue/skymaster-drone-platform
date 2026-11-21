# SkyMaster v0.1 · SS + 3D 无人机模型 联合里程碑

## ✅ 本轮完成

### SS · WebSocket 主动推 mission event（去掉 1.5s 轮询）

**后端**
| 文件 | 用途 |
|---|---|
| `app/services/mission_watcher.py` | 500ms 轮询 FakeDrone `/state`，检测 `mission_completed_at` 上升沿 → publish `mission.event.{sysid}` + `mission.event.all` |
| `app/api/v1/websocket.py` | 新增 `/api/v1/ws/events`，psubscribe `mission.event.all` |
| `app/main.py` | lifespan 挂载 MissionWatcher（env `ENABLE_MISSION_WATCHER=true`，默认开） |
| `tests/test_mission_watcher.py` | 隔离测试：伪 HTTP server + fakeredis 验证上升沿 |

**前端**
- `components/GlobalEventStream.tsx`：常驻组件，订阅 `/ws/events`；收到 `mission.completed` → `message.success("🎯 无人机 X 任务完成 · N/N")`
- 挂载点：`app/dashboard/live/page.tsx`（Spin 之外，全局生效）
- 断线自动重连，指数退避 500ms → 8s

**实测**
```
WS 连接 ─┐
         │
   派发 mission
         │
   等 0.9s
         │
   ✅ ws-rx: {"type":"mission.completed",
              "data":{"sysid":1,"mission_progress":"1/1", ...}}
```

原来的 1.5s 轮询保留作降级；主推送链路走 WS，延迟从 ~1.5s → **~0.3s**。

---

### A · 3D 无人机模型（Cesium primitives 版）

替换 CesiumMap 里的 `PointGraphics` 为 **BoxGraphics 机身 + 4 CylinderGraphics 螺旋桨**：

```
        ┌──[cylinder]──┐        ← Yellow prop
        │              │
     [box body 6×6×1.5] ← Cyan/Lime
        │              │
        └──[cylinder]──┘
```

- 尺寸：约 6m × 6m × 1.5m 主体，桨盘 4m
- `HeadingPitchRoll` yaw 每秒 2 rad，视觉上"转起来"
- Primary drone 绿色，其他青色
- 标签保留（`LabelGraphics`+背景块）

**不引外部 glTF 的理由**
- 零下载、零 CORS、零打包体积增加
- 依赖 `resium` 已有的 primitives 组件
- 视觉可辨识度足够（对比之前的圆点）

---

## 📊 测试
```
Backend  50 pass / 1 skip  (+1 test_mission_watcher.py)
Frontend tsc 0 error
```

---

## 累计能力（LL → SS + 3D）

| 里程碑 | 能力 |
|--------|------|
| LL     | 实时遥测 |
| MM     | 按钮控制 |
| NN     | 地图画任务 |
| OO     | SQLite 持久化 |
| PP     | 历史轨迹可视化 |
| QQ     | 相机跟随 |
| RR     | 完成事件（1.5s 轮询）|
| **SS** | **完成事件（WS 主动推）** |
| **3D** | **BoxGraphics + Cylinder 四旋翼模型** |

---

## 🎬 完整演示动线（一句话）

打开 `/dashboard/live`
→ 看到 2 台**四旋翼 3D 模型**在球面漂浮转桨
→ 点「跟随相机」跟着 primary 转
→ 打开「历史轨迹」看到彩色尾迹
→ 点「开始绘制」在地图上点 3 下
→ 点「派发」→ Toast 弹出「绘制模式关闭」→ 状态徽章绿色 mission 1/3 → 2/3 → 3/3 ✅
→ **同时** 屏幕右上角 Toast「🎯 无人机 1 任务完成 · 3/3」（**WS 推**，不是轮询）

---

## ⚠️ 遗留

- [ ] postgres:16 + TimescaleDB 生产落库（SQLite 是 dev 版）
- [ ] 轨迹逐帧生长动画（当前 3s 一批刷新）
- [ ] 4 桨独立转速可视化（当前整机 yaw）
- [ ] 真的 glTF 模型（若要更精细美术效果）

🐈
