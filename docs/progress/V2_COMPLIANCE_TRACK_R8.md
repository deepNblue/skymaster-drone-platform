# SkyMaster · v2.0 Compliance Track (R8) Copilot 审批 UI · Admin 搜索过滤/组织 CRUD · Grafana 角色审计面板

> 2026-07-10 03:27 UTC · R7 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. Copilot Approvals Inbox（前端 + 后端）

**后端** `app/api/v1/copilot.py`：
- 新增 `GET /copilot/approvals/pending?limit=50` — 返回状态为 `pending` 的 CopilotTrace 摘要
- **RBAC 过滤**：`admin` 看全组织；非 admin 仅看本 `org_id`
- 按 `started_at desc` 倒序，limit 200 上限

**前端** `components/ApprovalsInbox.tsx`：
- 15s 轮询待审批列表（无 WebSocket 依赖，纯 REST 简化）
- 每条：意图 tag（takeoff 红/land 橙/goto 蓝/rtl 紫/scan/photo 各色）+ trace_id 截前 8 位 + 时间 + prompt 摘要
- 批准按钮 → Popconfirm 二次确认 → `POST /traces/{id}/approve {decision:"approved"}`
- 驳回按钮 → Modal 输入原因 → `POST /traces/{id}/approve {decision:"rejected", comment}`
- 挂载在 `/dashboard/copilot` 左下 50% 面板

**lib/api.ts** 新增：`listPendingApprovals` / `approveTrace`

### 2. Admin 搜索/过滤/组织 CRUD

**后端** `app/api/v1/admin.py`：
- `GET /admin/users` 新增 3 个 query 参数：`q`（邮箱模糊）、`role`、`is_active`；limit 500
- `PATCH /admin/organizations/{id}` — 组织重命名（含冲突检查）
- `DELETE /admin/organizations/{id}` — 硬删除；**拒绝规则**：组织下有活跃用户则 409，强制先迁移

**前端** `app/admin/page.tsx`：
- 组织列表加编辑/删除按钮 + Popconfirm
- 新建/编辑组织复用同一 Modal
- 用户 Card extra 区新增：
  - 邮箱搜索框（`Input.Search`，实时过滤）
  - 角色下拉（viewer/operator/admin）
  - 状态下拉（在线/停用）
  - 新建按钮
- 4 个 filter state 全部作为 `useCallback` 依赖，改动自动重新拉取

**lib/api.ts** 新增：`updateOrganization` / `deleteOrganization`；`listUsers` 签名改为对象参数

### 3. Grafana 审计面板 `docker/grafana/dashboards/skymaster-audit.json`

**8 个 panel**：
| ID | Title | 类型 |
|---|---|---|
| 1 | 5min 审计量 | stat + 阈值绿/黄/红 |
| 2 | 5min GeoFence 拦截 | stat + 阈值绿/红 |
| 3 | 5min UOM 拒批 | stat + 阈值绿/橙 |
| 4 | 在线 WS 连接 | stat |
| 5 | 审计事件按角色 rate/s | timeseries stacked |
| 6 | HTTP p95 延迟 | timeseries |
| 7 | 操作分布按角色 · 1h | piechart |
| 8 | 违规 Top 10 · role×resource | table |

配套：
- `docker/grafana/dashboards/dashboards.yml` — provisioning provider
- `docker/grafana/datasources/datasources.yml` — Prometheus datasource
- docker-compose 已挂载 volumes 到这两个目录

### 4. 新增 Prometheus 指标（配合 R8 面板）

`app/services/metrics.py`：
- `skymaster_audit_events_total{actor_role, method}` — 审计事件计数（面板 5/7 主数据源）
- `skymaster_uom_rejections_total{reason}` — UOM 拒批（面板 3 数据源）
- `skymaster_ws_active_connections` — 汇总 WS 连接数（面板 4）

`app/services/audit_middleware.py`：
- 三条审计路径（memory sink / SQL / JSON log）末尾统一调用 `_bump_audit_metric()`
- HTTP method 从 `action` 前缀提取（e.g. "POST /copilot/traces/{id}/approve" → method="POST"）
- Prometheus 直接按 `actor_role` label 分组，无需额外聚合

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
| v2.0 R7 | WS 心跳/断线 + JWT 持久化 + 角色感知 + alembic 迁移 |
| **v2.0 R8** | **Copilot 审批 UI + Admin 搜索/CRUD + Grafana 角色审计** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] Copilot 审批操作也自动上报 `actor_role` 到审计（当前依赖中间件 JWT 提取，已 OK）
- [ ] Grafana 面板部署自动化验证（需实际 stack 起来跑一遍）
- [ ] UOM 拒批 reason 上报点接入 metrics（Counter 已定义未 wire 至业务点）
- [ ] Approvals Inbox 显示 org 名称而非 UUID
- [ ] alembic 迁移生成 CopilotTrace.org_id NOT NULL 约束（当前 nullable）
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R8 落地。
