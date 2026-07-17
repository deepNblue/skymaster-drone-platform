# SkyMaster · v2.0 Compliance Track (Round 2) 硬拦截 · 可视化 · 可观测

> 2026-07-10 02:00 UTC · 继续从 v2.0 蓝图落地
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. 合规硬拦截接入 `mission_dispatcher` (`sim/mission`)
- POST `/api/v1/sim/drones/{sysid}/mission` 派发前**强制**过 UOM + GeoFence
- 遇到 `no_fly` 违规 → **HTTP 451** `code=geofence_violation`
- 无 approved UOM 报备 → **HTTP 451** `code=uom_not_ready`
- 派发成功响应体新增 `compliance: {geofence, uom}` 摘要
- 新增 `skip_compliance=true` 逃生舱（仿真调试用）

### 2. Cesium 地图禁飞区红色多边形可视化
- `CesiumMap` 新增 `zones` prop + `GeoFenceZone` interface
- **红色半透明**：no_fly 禁飞区（附 ⛔ 标签）
- **黄色半透明**：height 限高区（附高度阈值标签）
- **橙色**：restricted 限飞区
- 前端 `/dashboard/live` 页首屏自动拉 `/geofence/zones` 覆盖到地球上

### 3. Prometheus `/metrics` 端点（v1.0 监控条）
- 零外部依赖，hand-rolled 计数器/直方图/仪表
- 指标：
  - `skymaster_http_requests_total{method,path,status}`（Counter）
  - `skymaster_http_request_duration_seconds{method,path}`（Histogram）
  - `skymaster_missions_dispatched_total`（Counter）
  - `skymaster_geofence_blocks_total{kind}`（Counter）
  - `skymaster_uom_reports_total{status}`（Counter）
  - `skymaster_ws_connections{channel}`（Gauge）
- 中间件 `MetricsMiddleware` 自动记 HTTP 指标
- UOM `approve/reject` 埋点、mission dispatch 拦截埋点
- 输出 `text/plain; version=0.0.4` 标准 Prometheus 格式

### 4. 测试单例状态隔离
- `conftest.py::client` fixture 每轮重置 `uom_adapter._adapter` / `geofence._engine`
- `UOM_AUTO_APPROVE=false` 测试默认关闭（避免并发提交竞态）
- 新增 `test_compliance_integration.py` (4 case) + `test_metrics.py` (2 case)

---

## 端到端 Flow（更新版）

```
用户在地图上点航点
   ↓
POST /api/v1/sim/drones/1/mission {waypoints:[...]}
   ↓
① GeoFence.check_waypoints ─┐
                             ├─→ no_fly? → 451 + 计数 geofence_blocks_total{kind=no_fly}
② UOM.check_ready_for_takeoff ─┤
                             ├─→ no approved report? → 451 + 计数 kind=uom_not_ready
③ 通过 → forward 到 FakeDrone HTTP
                             ↓
                     计数 missions_dispatched_total
                             ↓
                     记 audit_logs（Audit Middleware）
                             ↓
                     记 http_request_duration_seconds（Metrics Middleware）
                             ↓
返回 { ok, mode, compliance: { geofence, uom } }
```

---

## 前端最终形态

```
┌──────────────────────────────────────────────────────────┐
│    [🎯 跟随]                                [🛡 飞行报备]   │
│  ┌──────────┐  ┌── 禁飞区红色多边形 ⛔ ─┐  ┌────────────┐│
│  │🎮 SIM控制│  │  🚁 D1 3D 四旋翼      │  │✏️ 任务编辑 ││
│  │  mission │  │  🟠 D1 历史尾迹       │  │  绘制/派发 ││
│  │  3/3 ✅  │  │  🟡 限高区(120m) 标签 │  │┌──────────┐│
│  └──────────┘  └───────────────────────┘  ││📅 历史轨迹││
│                                            │└──────────┘│
│                                            └────────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## 累计能力对比

| 版本 | 里程碑 |
|---|---|
| v0.1 (base) | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence Engine + Audit Middleware |
| **v2.0 R2** | **合规硬拦截 + 禁飞区可视化 + Prometheus /metrics** |

---

## 测试统计

```
Backend total:  64 pass / 1 skip · +6 case
  · test_compliance_integration.py  4 (blocked_no_fly / blocked_no_uom / passes_with_uom / skip_flag)
  · test_metrics.py                 2 (endpoint / geofence_block_counter)
  · test_uom.py                     3 (unchanged, +auto_approve off)
  · test_geofence.py                3
  · test_audit_middleware.py        2
Frontend tsc: 0 error
Total new files this round: 3  (metrics.py, test_metrics.py, test_compliance_integration.py 重构)
```

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI/非 3D 范围内：**

- [ ] `docker-compose.prod.yml` — postgres:16 + timescaledb + redis:7 + minio + nginx（v0.5 部署条）
- [ ] GitHub Actions CI — pytest + tsc + build（v0.5 部署条）
- [ ] 前端 telemetry lag / mission fail rate 面板（对接 /metrics）
- [ ] JWT 里 org_id 真的过滤 drones/missions 列表（v1.0 多租户）
- [ ] RBAC roles（观察员/操控员/管理员）— v1.0 权限
- [ ] audit_logs 生产落库切通（当前 lifespan 里 `async_sessionmaker` 未挂 state）
- [ ] Geo-fence 生产 zone 库对接（AMS/民航局/EASA feed 或本地 JSON）

🐈 v2.0 R2 打入，路径已明确。
