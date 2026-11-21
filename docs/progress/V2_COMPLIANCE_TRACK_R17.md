# SkyMaster · v2.0 Compliance Track R17 · 飞行报备状态机 + 多主管拆分 + 起飞预检

> 2026-07-10 09:40 UTC · Track A 第一根桩
> 规格书 §3.14 "⭐ 平台核心壁垒"

---

## ✅ 本轮五件套

### 1. 数据模型
- **`FlightApproval`** — 一份报备的主表（title/purpose/pilot/aircraft/polygon/altitude/time_window/status/timeline）
- **`FlightApprovalAuthority`** — 每份报备扇出的 N 条主管审批子行
- Alembic **20260710_0011**：两表 + 7 索引

**Status Machine：**
```
draft → submitted → in_review → approved → flown → archived
                      │              │
                      └→ rejected    └→ cancelled
```

### 2. 主管路由引擎 `approval_router.py`
7 类主管静态目录 + 规则引擎：
- **UOM**（民航局） — 全国强制，任何飞行必带
- **local_police** — 属地公安，命中南宁/北京/上海 bbox 自动加
- **atc** — 空管，高度>120m OR 类别≠routine 触发
- **market_regulator** — 市监，机重≥15kg 触发
- **forestry** — 林草，命中保护区 bbox 触发
- **tourism** — 文旅，purpose 含"景区/公园/文旅/表演"触发
- **maritime** — 海事，沿海 bbox 触发

`category=emergency` 自动跳过 P2 主管，只留 P0/P1 强制项。

### 3. 起飞前智能预检 `preflight.py`
**8 项检查：**
1. 报备存在性
2. 报备状态 == approved
3. 时间窗（tz-aware 兼容 naive datetime）
4. 飞手执照
5. 无人机注册号
6. 保险单号（warn）
7. 计划高度 vs 报备最大高度
8. Remote ID 广播开关
9. 各主管审批 rollup

返回 `{ok, blocking, fail_count, warn_count, items[]}`，任一 fail 阻塞起飞。

### 4. REST API 10 端点 `approvals.py`
| 端点 | 说明 |
|---|---|
| GET  `/authorities/catalog` | 7 主管静态目录 |
| POST `/approvals` | 创建草稿 |
| GET  `/approvals` | 列出（可按状态过滤） |
| GET  `/approvals/{id}` | 详情（含 authorities） |
| PATCH `/approvals/{id}` | 编辑（仅 draft 可） |
| POST `/approvals/{id}/route` | 预览路由（不落库） |
| POST `/approvals/{id}/submit` | 提交 → 扇出主管 |
| POST `/approvals/{id}/authorities/{code}/decide` | 主管决策 |
| POST `/approvals/{id}/cancel` | 取消 |
| POST `/approvals/{id}/mark-flown` | 标记已飞行 |
| POST `/approvals/{id}/preflight-check` | 起飞预检 |

### 5. 前端 "飞行报备" 页 `/dashboard/approvals`
- **列表**：状态彩色 Tag + 主管数 + 快捷操作（提交/取消/已飞）
- **新建 Modal**：任务标题/作业性质/类别/飞手/机型/保险/最大高度/时间窗/多边形 JSON
- **详情 Modal**：
  - Descriptions：基本信息 + 状态 + 驳回原因
  - 各主管列表 + 每项 通过/驳回 按钮（demo 模拟主管回执）
  - 起飞预检结果面板（成功/警告/失败逐项）
  - Timeline 时间线（append-only 事件流）
- 侧栏新增菜单

---

## 测试统计

```
Backend:  124 pass (+8 flight_approvals) / 8 skipped · 全绿
Frontend: tsc 0 error
```

**测试覆盖：**
1. 主管目录暴露
2. 南宁 bbox + >120m 高度 → uom+local_police+atc 三主管
3. ≥15kg 机重 → market_regulator
4. 完整状态机（draft→submit→approve×N→approved→flown）
5. 驳回流（rejected + reject_reason 写入）
6. Preflight 阻断（4 项 fail: 状态/执照/注册/RemoteID）
7. draft 后不可编辑
8. cancel 流

**修复：** preflight 时区兼容（naive datetime → 强制 UTC）

---

## 规格书对齐

| §3.14.1 需求 | 状态 |
|---|---|
| 一份报备自动拆分至多主管 | ✅ |
| 各主管独立回执 → 汇总 rollup | ✅ |
| 状态机 draft→submitted→approved→flown→archived | ✅ |
| 起飞前智能预检 | ✅ |
| Nanning 试点属地路由 | ✅（bbox 静态命中） |
| 反向 Approval-as-a-Service | ⏳ 下一根桩 |
| 属地 RPA 引擎（无 API 用 RPA） | ⏳ 下一根桩 |

---

## 遗留 · 下一根桩（Track D · 三员分立 + 国密）

- [ ] 三员分立数据模型：`SystemOfficer` / `SecurityOfficer` / `AuditOfficer`
- [ ] 操作权限矩阵按角色隔离
- [ ] 国密 SM2 / SM3 / SM4 通道（用 gmssl / snowland-smx）
- [ ] 日志 SM4 加密 + SM3 完整性摘要
- [ ] Approval-as-a-Service 对外 API

🐈 v2.0 Track A · R17 落地。
