# SkyMaster · v2.0 Compliance Track (R10) JWT refresh · 我的账户 · 批量审批 · bcrypt 直连

> 2026-07-10 04:04 UTC · R9 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮五件套

### 1. JWT Refresh Token 后端
`app/services/auth.py` + `app/api/v1/auth.py`：
- `create_access_token()` 添加 `typ:"access"` claim
- **新增** `create_refresh_token()` — 14 天有效期（`jwt_refresh_days`），`typ:"refresh"`
- **`POST /auth/refresh`** — 输入 refresh_token，返回新的 access+refresh 对
  - `typ` 校验：拒绝 access token（返回 401）
  - **Token 旋转**：每次 refresh 都签发新 refresh 减少 replay 窗口
  - 重新查库校验用户状态（is_active/role/org 可能变更）
- **`POST /auth/password`** — 自服务改密（旧密码校验 + 新旧不同校验）
- `/auth/login` 响应新增 `refresh_token` 字段
- `is_active=false` 用户拒绝登录 & 拒绝 refresh

### 2. bcrypt 直连（passlib 移除）
`app/services/auth.py`：
- **背景**：passlib < 1.7.5 + bcrypt >= 4.1 兼容性 bug，`__about__` 属性被移除导致假报"password >72 bytes"
- 改直调 `import bcrypt` + `bcrypt.hashpw/checkpw`
- `_clamp()` 显式 UTF-8 截断到 72 字节（bcrypt 硬上限）
- 结果：73 pass 全绿 · 无兼容性坑

### 3. 前端 API 层自动 refresh
`frontend-v0.1/lib/api.ts` 完整重写：
- 401 响应触发**单次自动重试**流程：
  1. 用 `_tryRefresh()`（with in-flight 去重）拿 refresh_token 换新 access
  2. 更新 localStorage，用新 token 重放原请求
  3. 失败/无 refresh 才跳登录页
- `_refreshInflight` promise 防并发重复 refresh
- `original._retried` 标记防无限循环
- `login()` 自动持久化 `refresh_token` 到 localStorage
- 新增 `changePassword()` / `getMe()` API 函数

### 4. 前端"我的账户"页 `/dashboard/profile`
`app/dashboard/profile/page.tsx`：
- 顶部 Descriptions 展示邮箱/角色（彩色 tag）/org_id/状态（在线绿 · 停用红）
- `useEffect` 挂载时调 `getMe()` 刷新最新用户信息
- 修改密码表单：旧密码 + 新密码 + 确认新密码 + 一致性校验
- 密码策略 Alert：长度 ≥6，新旧必须不同
- Dashboard layout 用户菜单 "个人资料" 点击跳转此页
- Logout 处理器同步清理 `refresh_token`

### 5. Approvals 批量审批
**后端** `POST /api/v1/copilot/approvals/bulk`：
- Body: `{trace_ids: [...], decision: "approved"|"rejected", comment?}`
- 非 admin 只能操作本 org 内 trace（RBAC 复用 pending 过滤逻辑）
- 非 pending 状态自动跳过（结果里 `skipped`）
- 无效 UUID 静默跳过（防 400 卡死批量）
- 单 UPDATE + commit 而非 N 次

**前端** `ApprovalsInbox.tsx`：
- 每条前加 `Checkbox`，`selected: Set<string>` 管理选中
- Card extra 新增：**全选 · 批准(N) · 驳回(N)** 三按钮
- 全选按钮智能切换 "全选/取消全选"
- 空选中时按钮 disabled

**lib/api.ts** 新增：`bulkApproveTraces(traceIds, decision, comment?)`

---

## 测试统计

```
Backend total:  73 pass / 8 skipped · 全绿
Frontend tsc:   0 error
```

（+4 skip 是 test_auth_refresh.py 在 Postgres 缺席时跳过，符合预期）

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
| v2.0 R9 | UOM reason wire + WS 指标 wire + Approvals org 名 + CopilotTrace 非空 |
| **v2.0 R10** | **JWT refresh + 我的账户 + 批量审批 + bcrypt 直连** |

---

## 认证生命周期完整闭环

```
┌──────────────────────────────────────────────────────────────┐
│  1. Login       → access(60min) + refresh(14 天)             │
│  2. API 调用     → Bearer access; 401 触发 auto-refresh       │
│  3. Auto-refresh → 用 refresh 换新对(旋转)，重放原请求        │
│  4. Refresh 失效 → 清 storage 跳登录                          │
│  5. 密码修改     → /auth/password 旧密码校验 + 长度校验        │
│  6. Logout      → 双 token 清理                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] Refresh token 服务端 revocation list（当前无失效名单）
- [ ] 密码策略强化：大小写/数字/符号要求
- [ ] 双因素认证 (2FA/TOTP)
- [ ] `/auth/logout` 后端端点（配合 revocation list）
- [ ] Approvals 批量操作也写审计（当前仅单条走 middleware）
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R10 落地。
