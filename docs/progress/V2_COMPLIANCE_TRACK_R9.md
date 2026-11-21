# SkyMaster · v2.0 Compliance Track (R9) UOM reason wire · WS 连接指标 · Approvals org 名 · CopilotTrace.org_id 非空

> 2026-07-10 03:40 UTC · R8 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. UOM 拒批 reason → Prometheus wire
`app/services/uom_adapter.py::reject()`：
- 拒批文本 → 6 桶分类（防止 label 高基数爆炸）：
  - `geofence`（禁飞区/no_fly/no-fly 命中）
  - `altitude`（altitude/height/限高）
  - `license`（certificate/license/证件）
  - `weather`（wind/天气）
  - `airspace_conflict`（conflict/overlap）
  - `other`（其他）
- 自由文本原因仍完整存审计日志，Prometheus 只用有界 label
- 触发 `skymaster_uom_rejections_total{reason=<bucket>}` 计数

### 2. WebSocket 连接数指标 wire
`app/api/v1/websocket.py`：
- `_ws_metric_inc(channel)` / `_ws_metric_dec(channel)` 辅助函数
- `events_ws` endpoint：accept 后 `+events`，finally 前 `-events`
- `telemetry_ws` endpoint：accept 后 `+telemetry`，finally 前 `-telemetry`
- **双计数器**：
  - `skymaster_ws_connections{channel}` — 按 events/telemetry 分组
  - `skymaster_ws_active_connections` — 全平台汇总（Grafana 面板 4 数据源）
- 用 try/except 包裹，metrics 未启用也不影响 WS

### 3. Approvals Inbox 显示组织名
**后端** `copilot.py::list_pending_approvals`：
- 批量 fetch 涉及的 org names 到 dict → 单 query 而非 N+1
- 返回结构新增 `org_name` 字段（若 org_id 为空则为 null）

**前端** `ApprovalsInbox.tsx`：
- `PendingItem` 类型新增 `org_name: string | null`
- 列表标题多显示一个 cyan 组织 tag（无 org 则不显示）
- **好处**：admin 在 approve 前一眼看清 trace 归属，无需再对 UUID

**lib/api.ts** `listPendingApprovals` 返回类型同步更新

### 4. Alembic 迁移 20260710_0004 · CopilotTrace.org_id NOT NULL

`alembic/versions/20260710_0004_copilot_trace_org_not_null.py`：

**三阶段迁移**：
```
Step 1: 从 CopilotSession.org_id 回填 traces.org_id (JOIN UPDATE)
Step 2: 剩余 orphan trace → 建立哨兵组织 "__legacy_null_org__"
Step 3: ALTER COLUMN org_id NOT NULL + 联合索引 (org_id, status)
```

- 索引 `ix_copilot_traces_org_status` 加速 `pending approvals` 查询
- `ON CONFLICT DO NOTHING` 保证幂等（可重复运行）
- 完整 `upgrade()` / `downgrade()` 对称

---

## Prometheus 指标完整清单（R2 → R9）

| Metric | Labels | 说明 |
|---|---|---|
| `skymaster_http_requests_total` | method/status | HTTP 请求计数 |
| `skymaster_http_request_duration_seconds` | method | HTTP 延迟直方图 |
| `skymaster_missions_dispatched_total` | status | 任务派发 |
| `skymaster_geofence_blocks_total` | zone_kind | GeoFence 拦截 |
| `skymaster_uom_reports_total` | status | UOM 报备总量 |
| `skymaster_uom_rejections_total` ✨R8 | reason ✨R9 wire | UOM 拒批+原因分类 |
| `skymaster_audit_events_total` ✨R8 | actor_role/method | 审计事件按角色 |
| `skymaster_ws_connections` | channel ✨R9 wire | WS 连接按频道 |
| `skymaster_ws_active_connections` ✨R8 | (none) ✨R9 wire | WS 全平台汇总 |

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
| v2.0 R1 | UOM Mock + GeoFence + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus |
| v2.0 R3 | RBAC 三级 + audit 生产库 + CI |
| v2.0 R4 | k8s 探针 + Remote ID + 多租户 + Grafana |
| v2.0 R5 | 遥测→RID 联动 + Admin CRUD + Cesium 叠加 |
| v2.0 R6 | admin 前台 + WS 限流 + 生产禁飞区库 |
| v2.0 R7 | WS 心跳/断线 + JWT 持久化 + 角色感知 + alembic |
| v2.0 R8 | Copilot 审批 UI + Admin 搜索/CRUD + Grafana 角色审计 |
| **v2.0 R9** | **UOM reason wire + WS 指标 wire + Approvals org 名 + CopilotTrace 非空** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] Grafana 面板实际 stack 部署验证（Prometheus scrape + Grafana provision）
- [ ] Approvals Inbox 支持批量批准/驳回（当前逐条）
- [ ] 前端设置页 "我的账户" 修改密码/头像
- [ ] JWT refresh token endpoint（当前仅 access token）
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R9 落地。
