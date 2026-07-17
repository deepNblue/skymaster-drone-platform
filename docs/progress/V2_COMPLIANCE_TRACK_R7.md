# SkyMaster · v2.0 Compliance Track (R7) WS 心跳 · JWT 持久化 · 角色感知 · alembic 迁移

> 2026-07-10 03:16 UTC · R6 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮五件套

### 1. WebSocket 客户端心跳 & 状态机
`frontend-v0.1/lib/ws.ts`：
- **`WsState` 类型**：`connecting` / `open` / `reconnecting` / `closed`
- **客户端 heartbeat**：每 15s 发 `{type:"ping",ts}`（后端 heartbeat 30s，3× 安全余量）
- **stall 检测**：45s 无任何服务端帧 → 强制 close(4000) 触发重连
- **ping/pong 帧自动过滤**：不进 `onMessage` 回调
- 保留原指数退避重连（500ms → 30s，cap 8 次）
- 新增 `onState(cb)` 订阅接口 + `getState()` 快照接口

### 2. WSStatusBadge UI 组件
`frontend-v0.1/components/WSStatusBadge.tsx`：
- 四色状态徽章 + 图标：`connecting` 黄 / `open` 绿 / `reconnecting` 橙 / `closed` 灰
- Tooltip 悬浮显示 `drone_id + 状态`
- 通过 `subscription.onState(cb)` 订阅状态变化，自动 unsubscribe

### 3. JWT localStorage 持久化 + 角色感知
`frontend-v0.1/lib/store.ts` — Zustand store 重构：
- **`decodeJwtPayload(token)`**：客户端 base64 解 JWT payload（不验证签名，后端已验证）
- `setToken()` 自动从 JWT 提取 `sub / email / role / org_id` 并落 localStorage
- `user_profile` localStorage 键持久化用户资料
- **`hasRole(required)`** 方法：viewer(1) < operator(2) < admin(3) 数值比较
- `clear()` 一并清空 token + profile

**登录页** `app/login/page.tsx`：`localStorage.setItem` 移除，改由 `setToken()` 内部处理

### 4. RoleGate 组件（客户端角色门禁）
`frontend-v0.1/components/RoleGate.tsx`：
- Wrap 任意 admin-only UI
- 未登录：透传（依赖 API 401 拦截跳登录）
- 登录但角色不足：显示 `Alert` 「权限不足」提示（含当前角色与所需角色）
- **admin 页面已包裹**：`app/admin/page.tsx` 已加 `<RoleGate required="admin">`

### 5. Alembic 迁移 20260710_0003
`alembic/versions/20260710_0003_v2_r7_soft_delete.py`：
- `users.is_active` — Boolean NOT NULL DEFAULT TRUE + 索引 `ix_users_is_active`
- `audit_logs.actor_role` — String(30) NULL + 索引 `ix_audit_logs_actor_role`
- 完整 `upgrade()` / `downgrade()` 对称

**审计中间件同步**：
- `AuditLog.actor_role` 字段声明
- `_extract_actor()` 返回 `(uuid, role)` 二元组，从 JWT `role` claim 提取
- 落库/内存 sink/JSON 日志三条路径均携带 `actor_role`
- 便于后续按角色维度分析异常操作

---

## 前端类型 & 后端全绿

```
Backend total:  73 pass / 4 skipped
Frontend tsc:   0 error
```

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus |
| v2.0 R3 | RBAC 三级 + audit 生产库 + CI + 监控面板 |
| v2.0 R4 | k8s 探针 + Remote ID + 多租户 + Grafana |
| v2.0 R5 | 遥测→RID 联动 + Admin CRUD + Cesium 第三方叠加 |
| v2.0 R6 | admin 前台 + WS 限流 + 生产禁飞区库 |
| **v2.0 R7** | **WS 心跳/断线 UX + JWT 持久化 + 角色感知 + alembic 迁移** |

---

## 前端最终形态

```
┌──────────────────────────────────────────────────────────────┐
│  🔒 未登录 → /login  · 登录后 JWT 自动落 localStorage         │
│                                                              │
│  admin  → 全通，含 /admin CRUD 页                            │
│  operator → 无 /admin（RoleGate 拦截）                       │
│  viewer → 无 /admin，无派发按钮（后续接线）                    │
│                                                              │
│  实时地图右上角： 🟢在线 / 🟡连接中 / 🟠重连中 / ⚫已断开     │
│  服务端 30s / 客户端 15s 心跳 · 45s 无响应强制重连             │
└──────────────────────────────────────────────────────────────┘
```

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] 前端 Copilot 页面接线 Approvals 端点（v0.1 → v0.2 UX）
- [ ] Admin 用户搜索/过滤（当前仅 org_id 过滤）
- [ ] 前端 org 编辑/删除（当前仅新建）
- [ ] Grafana dashboard 增加"按角色分组"审计 panel
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R7 落地。
