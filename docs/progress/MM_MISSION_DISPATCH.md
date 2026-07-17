# SkyMaster v0.1 · MM 里程碑 — Mission Dispatch 端到端

## ✅ 新增能力：仿真无人机双向指令通道

前端点按钮 → Backend Sim API → FakeDrone HTTP → 遥测反馈路径已完全打通。

```
Frontend button (goto/mission/rtl)
    │
    ▼   POST /api/v1/sim/drones/{sysid}/goto
Backend Sim Router (proxy)
    │
    ▼   POST http://127.0.0.1:15001/command
FakeDrone HTTP command server (in-process)
    │
    ▼   state.mode = "goto", state.goto_target = Position
FakeDrone flight-pattern loop
    │
    ▼   _fly_to() @ 20 m/s
MAVLink UDP → MavlinkConnector → Redis Stream+PubSub
    │
    ▼
WebSocket /api/v1/ws/telemetry/{sysid}
    │
    ▼
CesiumMap 实时看到无人机移动到目标
```

## 📊 实测结果

### MM 端到端验证（`/tmp/mm_verify.py`）
```
初始位置        : (39.9048021, 116.4082689)
goto  →         : {'lat': 39.92, 'lng': 116.43, 'alt': 150}
API 响应        : {'ok': True, 'mode': 'goto'}
5s 后位置       : (39.9052768, 116.4089403)
─────────────────────────────────────────────
位移距离        : 78.0 m   ← 15 m/s × 5s
距目标点        : 2432.9 m ← 还剩 2.4km，符合真实飞行速度
```

### 单元测试
```
tests/test_sim.py       ✅ 7 passed
tests/test_e2e_simulated.py ✅ 3 passed
tests/  overall         ✅ 46 passed / 1 skipped
```

## 🧩 新增/改动

### 后端
| 文件 | 变更 |
|---|---|
| `scripts/fake_drone.py` | **重写** — 新增 `DroneState`、goto/mission/rtl 3 种动态模式、`_fly_to()` 惯性运动、`_CommandServer` HTTP 命令端点 |
| `app/api/v1/sim.py` | **新增** — 6 个仿真控制端点（drones/state/goto/mission/rtl/mode/arm/disarm） |
| `app/api/v1/router.py` | 挂载 sim router |
| `app/services/mavlink_connector.py` | 补充 `send_command()` / `send_mission_items()` 供真实 MAVLink 场景使用 |
| `scripts/dev_stack.py` | 默认设置 `SIM_DRONES=1:15001,2:15002` |
| `start_demo.py` | fake_drone 启动加 `--command-http` 端口 |
| `tests/test_sim.py` | 7 项单测覆盖 sim router |

### 前端
| 文件 | 变更 |
|---|---|
| `components/SimControlPanel.tsx` | **新增** — 悬浮控制面板：下拉选无人机、GOTO 三输入框、派发任务/RTL/悬停/画圆按钮、状态徽章（ARMED / mode / mission progress）实时轮询 |
| `app/dashboard/live/page.tsx` | 挂载 SimControlPanel，与选中无人机联动 |

## 🎮 演示流程（浏览器）

1. Windows 打开 `http://localhost:3000/dashboard/live`
2. 左上角出现「🎮 仿真控制」面板，两架无人机可选
3. 点击「派发任务」→ 弹窗确认 → 无人机开始按 3 航点飞行
4. 状态徽章实时显示 `mission 1/3 → 2/3 → 3/3`
5. 点「RTL」→ 无人机原速率返回起点
6. GOTO 手动输入经纬度 → 点「飞到此点」→ 观察 CYAN 点在地图上移动

## 🐛 修复

- **飞行速度太慢** — goto/mission/rtl 原用固定 dt=0.1s 但没乘 max_speed，实测 5s 只移动 21m；改为 `dt=interval_ms/1000` + `max_speed=20 m/s` → 5s 移动 78m ✅
- **create_app 不存在** — tests/test_sim.py 用 `from app.main import app`

## ⚠️ 遗留

- [ ] 前端 CesiumMap 未定位到 GOTO 目标（可加 flyTo 动画）
- [ ] mission 完成后没通知前端（可加 WS event）
- [ ] TelemetryConsumer 落库仍需 postgres:16

🐈
