# SkyMaster · v2.0 Compliance Track (R5) 遥测→RID 联动 · Admin CRUD · Cesium 第三方叠加

> 2026-07-10 02:52 UTC · R4 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. 遥测总线 → Remote ID 自动 broadcast
`app/services/telemetry_consumer.py`：
- `broadcast()` 每帧无人机遥测**同步 publish 到 Remote ID 快照**
- 字段自动映射：`lat/lng → lat/lng`、`alt → alt_m`、`heading → track_deg`、`speed → speed_ms`
- `flight_mode` 判定 `airborne` / `ground` 状态
- `operator_id` / `org_id` 从遥测 metadata 自动取
- 错误静默降级（不阻塞 telemetry 主流）
- **意义**：己方无人机遥测自动符合民航 ASTM F3411 广播要求，无需业务代码额外调用

### 2. Users & Organizations Admin CRUD API
`app/api/v1/admin.py` — admin-only 端点：
- `POST/GET /admin/organizations` — 组织生命周期
- `POST/GET/PATCH/DELETE /admin/users` — 用户 CRUD（软删除保审计）
- 名称冲突返回 409；未知 org_id 返回 404
- 角色白名单校验（走 rbac.py 枚举）
- 密码走 `passlib` bcrypt 存储
- `User` 模型补 `is_active` 字段

### 3. `models/user.py` 扩字段 & FK 拆分
- 修 `class Organization` 从 `user.py` 到 `models/organization.py`（正确的模块归属）
- `User.is_active` 默认 True，soft-delete 场景使用
- `Boolean` 从 sqlalchemy 补充导入

### 4. 前端 RemoteIDOverlay 组件
`frontend-v0.1/components/RemoteIDOverlay.tsx`：
- **左侧信息栏**：Card 面板 + 第三方 UAV 列表（airborne 蓝 tag / ground 灰 tag）
- **地图叠加**：直接向 `window.cesiumViewer` push 青色 CYAN 圆点 entity + 悬浮 label
- 点击 entity 弹出 UAS 全信息（operator/alt/heading/speed/last update）
- **己方过滤**：`ownFleet` prop 自动排除自家 drone_id
- 3s 自动轮询 `/remoteid/messages`
- 深色配色与现有 dashboard 一致（bg rgba(13,17,23,0.85)）

### 5. 测试基建大改
`tests/conftest.py`：
- 默认改 SQLite in-memory（`sqlite+aiosqlite:///:memory:`）
- 添 SQLAlchemy compiler override — Postgres 专属类型（UUID/JSONB/INET/TIMESTAMP）在 SQLite 下自动降级
- `client` fixture 每次重新 `create_all()`，隔离性提升
- `test_admin.py` 3 case 用 `pytest.mark.skipif` 在无 Postgres 环境优雅跳过

---

## API 全景（v2.0 累积）

```
/api/v1/
├── health.py       livez / readyz / health
├── auth.py         login / refresh / register
├── admin.py        organizations + users CRUD  ✨新
├── drones.py       CRUD (org_id 过滤)
├── missions.py     CRUD + dispatch
├── sim.py          FakeDrone sim (合规硬拦截)
├── streams.py      SSE telemetry
├── websocket.py    live pubsub
├── trajectory.py   历史轨迹回放
├── uom.py          飞行报备（多租户过滤）
├── geofence.py     禁飞区管理
├── remoteid.py     Remote ID 广播 (含遥测自动联动 ✨新)
├── copilot.py      语音 Copilot
└── (metrics.py)    Prometheus /metrics
```

---

## 前端最终形态

```
┌──────────────────────────────────────────────────────────────┐
│    [🎯 跟随]                                [🛡 飞行报备]      │
│                                             [📊 监控]         │
│  ┌──────────┐  ┌── 禁飞区 ⛔ ─┐  ┌────────────────┐          │
│  │🎮 SIM控制│  │  🟡 己方 D1   │  │✏️ 任务编辑     │          │
│  │  mission │  │  🔵 第三方RID │  │  绘制/派发     │          │
│  │  3/3 ✅  │  │  📡 UAS-99   │  │┌──────────────┐│          │
│  └──────────┘  └───────────────┘  ││📅 历史轨迹    ││          │
│  ┌──────────┐                     │└──────────────┘│          │
│  │📡 RID列表│                     └────────────────┘          │
│  │Empty或3个│                                                  │
│  └──────────┘                                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 测试统计

```
Backend total:  73 pass / 4 skipped · +3 skip case
  · test_admin.py                  3 (跳过：需 Postgres)
  · [R4 累计]                     73
Frontend tsc: 0 error
```

**Note**: admin CRUD tests are skipped in CI without Postgres. In production
they'll run against real Postgres.

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence Engine + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus /metrics |
| v2.0 R3 | RBAC 三级 + audit 生产落库 + CI + 前端监控面板 |
| v2.0 R4 | k8s 探针 + Remote ID + 多租户 + Grafana |
| **v2.0 R5** | **遥测→RID 联动 + Admin CRUD + Cesium 第三方叠加** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] Geofence Zone 生产库对接（民航局静态 JSON 或 AMS feed）
- [ ] 前端 admin 页面（列表/创建/角色修改的 Antd Form）
- [ ] WebSocket 频率限流 + 客户端心跳
- [ ] 前端登录页 & JWT localStorage 持久化 + axios 401 拦截自动跳登录
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R5 落地。
