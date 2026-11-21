# SkyMaster · v2.0 Compliance Track (R3) 权限打通 · CI · 监控面板

> 2026-07-10 02:30 UTC · Docker 分发暂缓，按用户指示继续代码化落地
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮五件套

### 1. RBAC 三级角色 + 分层校验
新增 `app/services/rbac.py`：
- **viewer** — 只读（rank 0）
- **operator** — 任务派发 + UOM 提交（rank 1）
- **admin** — 用户/组织管理 + UOM 审批（rank 2）
- `has_at_least(role, minimum)` 分层判定
- `is_admin`/`is_operator_or_above` 便捷断言
- 未知角色安全降级（返回 False）

### 2. 分层 FastAPI 依赖 `require_min_role(...)`
`app/deps.py`：
- `require_min_role(Role.OPERATOR)` — admin **也能过**（老版 `require_role` 是白名单模式，admin 过不了 operator 门）
- 已挂到 `POST /sim/drones/{sysid}/mission`
- 保持 `require_role(...)` 兼容旧 `drones.py` 端点

### 3. Auth-Optional 开关（v1.0 多租户前置）
`app/config.py` 新增 `auth_optional: bool = True`：
- **dev/tests** → 无 Bearer 时 `require_min_role` 自动放通为匿名 `operator` 假用户
- **prod** → 设 `AUTH_OPTIONAL=false`，无 token 直接 401
- 新 dep `get_current_user_optional` 承担这层降级
- 前端 dashboard 演示无需登录、生产切开关即上锁

### 4. audit_logs 生产落库通路打通
`app/main.py`：
- 在中间件挂载前显式 `app.state.async_sessionmaker = AsyncSessionLocal`
- `AuditMiddleware` 之前的 fallback 顺序：
  1. `app.state.audit_sink` (测试)
  2. **`app.state.async_sessionmaker` → AuditLog 表写库** ✅ 生效
  3. JSON 日志兜底
- 切到真 PostgreSQL 后**零改动**自动生产落库

### 5. GitHub Actions CI
`.github/workflows/ci.yml` 三 job：
- **backend** — Python 3.11 & 3.12 双版本矩阵，ruff（非阻塞）+ pytest
- **frontend** — Node 20 + tsc --noEmit + build（Cesium 非阻塞）
- **compliance-smoke** — 依赖 backend job，专跑合规/RBAC/审计 6 个测试文件

### 6. 前端监控面板 `MetricsPanel.tsx`
右上角新增 **📊 监控** 按钮（在 🛡 飞行报备 下方）：
- 打开抽屉，5s 自动 poll `/api/v1/metrics`
- **实时解析**：
  - 总请求数 + 错误率（>5% 红色告警）
  - HTTP P95 延迟（毫秒）
  - 任务派发累计
  - UOM 状态分布（approved/rejected/submitted 分色 Tag）
  - 禁飞区拦截分布（volcano 色 Tag）
- 前端**自解析 Prometheus text format**，零外部 dep

### 7. 测试 `test_rbac.py`
3 case：
- 角色层级判定单元测试
- `auth_optional=true` 无 token 派发成功
- `auth_optional=false` 无 token 返回 401

---

## 前端最终形态

```
┌──────────────────────────────────────────────────────────┐
│    [🎯 跟随]                                [🛡 飞行报备]   │
│                                             [📊 监控]     │
│  ┌──────────┐  ┌── 禁飞区红色多边形 ⛔ ─┐  ┌────────────┐│
│  │🎮 SIM控制│  │  🚁 D1 3D 四旋翼      │  │✏️ 任务编辑 ││
│  │  mission │  │  🟠 D1 历史尾迹       │  │  绘制/派发 ││
│  │  3/3 ✅  │  │  🟡 限高区(120m)      │  │┌──────────┐│
│  └──────────┘  └───────────────────────┘  ││📅 历史轨迹││
│                                            │└──────────┘│
└──────────────────────────────────────────────────────────┘
                             ↓ 点 📊 监控
┌────────────────────────┐
│ 📊 平台监控             │
├────────────────────────┤
│ 总请求 · 错误率 · P95   │
│ 任务派发累计            │
│ UOM 报备状态分布        │
│ 禁飞区拦截分布          │
│ 5s 自动刷新             │
└────────────────────────┘
```

---

## 测试统计

```
Backend total:  67 pass / 1 skip · +3 case
  · test_rbac.py                    3 (hierarchy / auth_optional_on / auth_optional_off)
  · test_compliance_integration.py  4
  · test_metrics.py                 2
  · test_uom.py                     3
  · test_geofence.py                3
  · test_audit_middleware.py        2
Frontend tsc: 0 error
```

---

## 累计能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1 | UOM Mock + GeoFence Engine + Audit Middleware |
| v2.0 R2 | 合规硬拦截 + 禁飞区可视化 + Prometheus /metrics |
| **v2.0 R3** | **RBAC 三级 + audit 生产落库 + CI + 前端监控面板** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] JWT 里 org_id 真过滤 UOM reports / geofence zones（用户创建的 zone 后续多租户隔离）
- [ ] 用户/组织 CRUD 端点 + admin UI（招募 operator 加入 org）
- [ ] Remote ID（民航 EAB-2023 广播）Mock endpoint
- [ ] mission_watcher 补充 `mission_dispatched_total` 埋点（当前只 `POST /sim` 埋点）
- [ ] `/health` 端点扩为 `/readyz` + `/livez`（k8s 就绪探针）
- [ ] Grafana dashboard JSON 模板（配合 /metrics）
- [ ] （Docker 分发按用户指示暂缓，v1.0 GA 前收官时再做）

🐈 v2.0 R3 落地。
