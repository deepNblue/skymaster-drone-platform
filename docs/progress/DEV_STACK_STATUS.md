# SkyMaster v0.1 · 前后端全链路仿真联调交付

## ✅ 联调状态：LIVE
Demo 栈已在本机常驻运行，PID → `/tmp/skymaster-demo.pids`

| 组件 | 地址 | 状态 |
|---|---|---|
| Backend | http://localhost:8000/docs | ✅ HTTP 200 |
| Frontend | http://localhost:3000 | ✅ HTTP 200 |
| Live Map | http://localhost:3000/dashboard/live | ✅ 已挂载 CesiumMap |
| Drone Beijing | sysid=1, circle @ 39.90/116.41 | ✅ 7 msg/3s |
| Drone Chengdu | sysid=2, line @ 30.57/104.07 | ✅ 6 msg/3s |

## 🎯 本轮新增/改动

### 前端 CesiumMap 多机联动
- **`components/CesiumMap.tsx`** 支持 `droneIds: string[]` 车队渲染
  - 每架无人机独立 Entity + Label
  - 主机 LIME 色高亮，其余 CYAN
  - 每架独立 WS 订阅，实时同步
- **`lib/ws.ts`** 
  - `resolveWsBase()` 默认拼 `/api/v1` 前缀（后端 mount 位置）
  - `normalizeTelemetry()` 兼容 dev_stack 的 `{type, ts, data:{...}}` 三层结构
  - 数字字段强制 `Number()` 转换
- **`app/dashboard/live/page.tsx`** 
  - drones API 401 时降级为 demo 无人机 `{id:'1', sn:'FAKE-01'}`
  - 保证纯前端环境也能看到地图

### 端到端启动
- **`start_demo.py`** 一键起 backend + 2 架 fake_drone + frontend
- **`/tmp/LL_e2e.py`** 全链路自动化冒烟脚本

## 📊 实测（LL 联调结果）
```
✅ backend :8000 ready
✅ fake_drone (sysid=1)
✅ frontend :3000 built + served in 20s
✅ WS /api/v1/ws/telemetry/1 → 5 msg / 6s
✅ /dashboard/live HTTP 200 (React hydrated)
```

多机 stress：
```
sysid=1 (Beijing circle): 7 msgs / 3s
sysid=2 (Chengdu line):   6 msgs / 3s
lat=39.9047225 lng=116.4064474 (北京实时)
lat=30.5728000 lng=104.0713426 (成都东进)
```

## 🌐 浏览器人工验证入口
1. Windows 浏览器打开 `http://localhost:3000`
2. 若未登录：直接访问 `/dashboard/live`（drones 降级）
3. 期望：Cesium 地图上北京+成都各一个 CYAN/LIME 点 100ms 频率移动
4. 后端日志 `/tmp/demo-backend.log`
5. 停止：`while read L; do kill -9 ${L#*=} 2>/dev/null; done < /tmp/skymaster-demo.pids`

## 🐛 已修 bugs
1. WS 路径缺 `/api/v1` 前缀 → 客户端 403
2. WS payload 是嵌套 `data: {lat: "39.9"}` 字符串，地图组件用 `typeof lat === 'number'` 判断永远为 false
3. `useEffect(droneIds)` 引用类型依赖 → 用 `JSON.stringify` 稳定化
4. drones API 401 阻断了整个 live 页面渲染 → 加降级 fallback

## ⚠️ 遗留
- [ ] 生产环境 WS 鉴权收紧（dev 允许 token=None）
- [ ] TelemetryConsumer 落库还需 postgres:16（SQLite 无 UUID/JSONB）
- [ ] fake_drone 只是单向发送，不响应 COMMAND_LONG（mission dispatch 待打通）

🐈
