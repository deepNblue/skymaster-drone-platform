# SkyMaster · v2.0 Compliance Track (R4) 探针 · RID · 多租户 · Grafana

> 2026-07-10 02:36 UTC · 继续从 R3 推进（Docker 分发按用户指示暂缓）
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮五件套

### 1. K8s 就绪探针 `/livez` + `/readyz`
`app/api/v1/health.py`：
- **`/livez`** — 只要进程活着就 200 `{"status":"alive"}`，从不 touch 下游
- **`/readyz`** — DB + Redis 双检，都通 200 `{"status":"ready"}`；任一挂 → **HTTP 503**
- 保留 legacy `/health` 全量详细状态（向后兼容）
- 生产 k8s / systemd 直接绑 livez+readyz

### 2. Remote ID 广播 Mock（民航 ASTM F3411-22a / EASA EAB-2023）
`app/services/remoteid.py` + `app/api/v1/remoteid.py`：
- 数据结构完整符合 F3411-22a §5.4 Basic ID + Location
- 字段：`uas_id`, `uas_id_type`, `lat/lng/alt`, `track_deg`, `speed_ms`, `vertical_rate_ms`, `height_agl_m`, `operator_id`, `status`, `home_lat/lng`
- **过期机制**：>30s 未更新自动清出快照（符合 ASTM 建议）
- Endpoints:
  - `GET  /remoteid/messages`（第三方 ATM/民航局稽查拉取）
  - `GET  /remoteid/messages/{uas}`
  - `POST /remoteid/broadcast`（operator role，未来接 mission_watcher）
  - `DELETE /remoteid/messages/{uas}`（admin）
  - `POST /remoteid/_test/clear`

### 3. UOM 多租户 org_id 隔离
- `uom_adapter.list_all(status, operator_id)` 新增 operator 过滤
- `GET /uom/reports?operator_id=xxx` 支持显式过滤
- **RBAC 边界**：非 admin 用户强制作用域到自己 `org_id`（忽略 query 参数）；admin 可跨租户查询
- 匿名 demo 用户保持全量可见（tests 通过）
- 响应体新增 `scoped_by` 字段暴露实际作用域

### 4. Grafana Dashboard 模板
`deploy/grafana/skymaster-dashboard.json`：
- 8 个面板：
  - **Stat**：任务派发累计 / 错误率(5m) / P95 延迟 / WS 在线数
  - **TimeSeries**：HTTP 请求速率(按 status) / 拦截速率(按 kind)
  - **BarGauge**：UOM 报备状态累计分布
  - **Heatmap**：HTTP 延迟热力
- 阈值告警：错误率 >5% 红 · P95>2s 红 · P95>0.5s 黄
- 5s 自动刷新 · schemaVersion 39 (Grafana 10.x+)
- 用户导入：Dashboards → Import → 上传 JSON

### 5. 测试覆盖
- `test_health_and_remoteid.py`（4 case）
  - `/livez` 恒 200
  - `/readyz` 200 或 503 结构验证
  - Remote ID broadcast → query → 404 全链路
  - 无 UAS 返回空数组
- `test_uom_multitenant.py`（2 case）
  - 无 scope 时全量可见
  - `?operator_id=xxx` 精确过滤 + `scoped_by` 回响

---

## API 全景（v2.0 累积）

```
/api/v1/
├── health.py       livez readyz health
├── auth.py         login/refresh/register
├── drones.py       CRUD (org_id 过滤)
├── missions.py     CRUD + dispatch
├── sim.py          FakeDrone sim + mission dispatch (合规硬拦截)
├── streams.py      SSE telemetry
├── websocket.py    live pubsub
├── trajectory.py   历史轨迹回放
├── uom.py          飞行报备（多租户过滤 ✨新）
├── geofence.py     禁飞区管理
├── remoteid.py     Remote ID 广播 ✨新
├── copilot.py      语音 Copilot (v0.1)
└── (metrics.py)    Prometheus /metrics
```

---

## 测试统计

```
Backend total:  73 pass / 1 skip · +6 case
  · test_health_and_remoteid.py   4 (livez / readyz / rid_full_cycle / rid_empty)
  · test_uom_multitenant.py       2 (all_visible / filter_by_op)
  · [R3 前累计]                   67
Frontend tsc: 0 error
```

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence Engine + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus /metrics |
| v2.0 R3 | RBAC 三级 + audit 生产落库 + CI + 前端监控面板 |
| **v2.0 R4** | **k8s 探针 + Remote ID + 多租户 + Grafana** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] mission_watcher 接入 Remote ID → 无人机遥测自动 broadcast
- [ ] 用户/组织 CRUD 端点 + admin UI（前端 admin 页面）
- [ ] Geofence Zone 生产库对接（民航局静态 JSON 或 AMS feed）
- [ ] 前端 Remote ID 层级：Cesium 地图上叠加第三方无人机（另 org 的 aircraft）
- [ ] WebSocket 广播频率限流 + 客户端心跳
- [ ] 前端 admin 登录页 & JWT 持久化 + 401 拦截自动跳登录
- [ ] （Docker 分发按你的指示暂缓，v1.0 GA 前收官时再做）

🐈 v2.0 R4 落地。
