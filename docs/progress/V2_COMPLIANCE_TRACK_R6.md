# SkyMaster · v2.0 Compliance Track (R6) admin 前台 + WS 限流 + 生产禁飞区

> 2026-07-10 03:00 UTC · R5 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. 前端 Admin 管理后台页
`frontend-v0.1/app/admin/page.tsx`：
- **两栏布局**：左 8/24 组织管理 · 右 16/24 用户管理
- 组织：新建/列表；点击行可过滤右侧用户列表
- 用户：新建/编辑/停用（软删除）；角色 tag 三色（admin 红/operator 蓝/viewer 灰）
- 表单校验（email 格式、密码 ≥6 字符、组织名 ≥2 字符）
- Modal 表单 + AntD Popconfirm 二次确认
- 已在侧栏菜单注入「管理后台」入口

**lib/api.ts** 新增：`listOrganizations` / `createOrganization` / `listUsers` / `createUser` / `patchUser` / `deactivateUser`

### 2. WebSocket 广播频率限流
`app/api/v1/websocket.py`：
- `WS_RATE_LIMIT_HZ = 20`（每 socket 20 帧/秒 = 每 50ms 1 帧）
- `time.monotonic()` 内联节流，超频帧直接丢弃（last-write-wins）
- **理由**：无人机 IMU 可达 200Hz，浏览器渲染最多 60Hz，服务端丢帧比客户端丢帧省带宽
- 保留 `HEARTBEAT_INTERVAL_S=30`（心跳）+ 指数退避重连（backoff 1s→30s）

### 3. 生产禁飞区静态库
`app/services/geofence_zones.py` + `deploy/geofence/zones.zh_cn.json`：
- **10 个生产级 zone**（真实坐标）：
  - `no_fly`（7个）：天安门、中南海、首都/虹桥/白云/宝安机场净空 + 北京市区限高 120m
  - `height`（3个）：深圳福田 CBD 120m、上海陆家嘴 CBD 120m、成都天府广场 100m
- 优先级顺序：`GEOFENCE_ZONES_FILE` env → `deploy/geofence/zones.zh_cn.json` → 内置 fallback
- 字段白名单机制：JSON 里 `authority` 权威依据仅用于文档展示，不进 Zone dataclass
- `restricted` kind 自动映射为 `height`（backward compat）

### 4. GeoFence 引擎 loader 重构
`app/services/geofence.py`：
- 移除 `_SEED_ZONES` 硬编码 → 委托给 `geofence_zones.load_zones()`
- `GEOFENCE_EXTRA_ZONES_FILE` 保留，用于在生产库之上叠加临时管制区（如大型活动临时限飞）

---

## API 全景（v2.0 累积）

```
/api/v1/
├── health.py       livez / readyz / health
├── auth.py         login / refresh / register
├── admin.py        organizations + users CRUD  (前端接入 ✨新)
├── drones.py       CRUD (org_id 过滤)
├── missions.py     CRUD + dispatch
├── sim.py          FakeDrone sim (合规硬拦截)
├── streams.py      SSE telemetry
├── websocket.py    live pubsub (20Hz 限流 ✨新)
├── trajectory.py   历史轨迹回放
├── uom.py          飞行报备（多租户）
├── geofence.py     禁飞区管理 (10 生产 zone ✨新)
├── remoteid.py     Remote ID 广播 (遥测自动联动)
├── copilot.py      语音 Copilot
└── (metrics.py)    Prometheus /metrics
```

---

## 禁飞区最终清单

| ID | Kind | 位置 | 限制 |
|---|---|---|---|
| no-fly-tiananmen | no_fly | 天安门核心区 | 0m |
| no-fly-zhongnanhai | no_fly | 中南海 | 0m |
| no-fly-pku-airport | no_fly | 首都机场 5NM | 0m |
| no-fly-hongqiao-airport | no_fly | 虹桥机场 5NM | 0m |
| no-fly-baiyun-airport | no_fly | 白云机场 5NM | 0m |
| no-fly-shenzhen-airport | no_fly | 宝安机场 5NM | 0m |
| bj-height-120 | height | 北京市区 | 120m |
| restricted-shenzhen-cbd | height | 深圳福田 CBD | 120m |
| restricted-lujiazui | height | 上海陆家嘴 CBD | 120m |
| restricted-tianfusquare | height | 成都天府广场 | 100m |

---

## 测试统计

```
Backend total:  73 pass / 4 skipped · 全绿
Frontend tsc:   0 error
```

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence Engine + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus /metrics |
| v2.0 R3 | RBAC 三级 + audit 生产落库 + CI + 前端监控面板 |
| v2.0 R4 | k8s 探针 + Remote ID + 多租户 + Grafana |
| v2.0 R5 | 遥测→RID 联动 + Admin CRUD + Cesium 第三方叠加 |
| **v2.0 R6** | **admin 前台 + WS 限流 + 生产禁飞区库** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] WebSocket 客户端心跳/断线重连 UX 优化（前端）
- [ ] JWT localStorage 持久化 + 角色感知 UI 门禁
- [ ] 前端 Copilot 页面接线 Approvals 端点
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅
- [ ] alembic 迁移脚本生成 admin 相关字段（is_active）

🐈 v2.0 R6 落地。
