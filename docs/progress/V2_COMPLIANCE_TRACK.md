# SkyMaster · v2.0 Compliance Track (Module ①) 第一根桩

> 2026-07-10 · 从 v0.1 稳定核向 v2.0 蓝图推进的第一次代码化落地
> 范围严格锁死：**非 AI / 非 3D-4D**，聚焦规格书 §3.14 v2.0 ① + v1.0 UTM + v1.0 等保三件套

---

## ✅ 本轮交付三件套

| 模块 | 定位 | 状态 |
|---|---|---|
| **UOM Adapter** | v2.0 ① 飞行报备 Mock 审批 | ✅ 全流程通 |
| **GeoFence Engine** | v1.0 UTM 电子围栏 | ✅ 4 seed zones · 3 kind |
| **Audit Middleware** | v1.0 等保 全审计 | ✅ Mutating 请求自动落库 |

---

## 1. UOM Mock Adapter · v2.0 Module ①

### 后端
| 文件 | 用途 |
|---|---|
| `app/services/uom_adapter.py` | 内存 + SQLite 持久化的模拟审批 |
| `app/api/v1/uom.py` | 6 endpoint REST |

### 状态机
```
DRAFT ─submit()→ PENDING ─approve()→ APPROVED ──✈ takeoff
   │                │
   │                └─reject()→ REJECTED
   └─cancel()→ CANCELLED / EXPIRED (超时自动)
```

### REST endpoint
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/v1/uom/reports` | 提交报备（PENDING 起步） |
| GET  | `/api/v1/uom/reports?status=pending` | 列表（可 filter） |
| GET  | `/api/v1/uom/reports/{id}` | 详情 |
| POST | `/api/v1/uom/reports/{id}/approve` | 批准 → 生成审批号 `UOM-{ts}-{id[:8]}` |
| POST | `/api/v1/uom/reports/{id}/reject` | 驳回（附 reason） |
| POST | `/api/v1/uom/reports/{id}/cancel` | 撤销 |
| POST | `/api/v1/uom/check` | **飞行前合规检查**：给一个 mission_area 多边形返回覆盖它的 approved 报备 |

### 自动审批循环
- 后台 asyncio 任务每 1s 扫一次 PENDING
- 环境变量 `UOM_APPROVAL_DELAY_S` 控制模拟审批延迟（默认 3s）
- `UOM_AUTO_APPROVE=false` 关闭自动审批（人工审批场景）

### 关键校验
- polygon ≥ 3 点
- end_ts > start_ts
- 0 < max_alt_m ≤ 500
- pending 才能 approve/reject
- draft/pending 才能 cancel

### 测试
`tests/test_uom.py` · 3 case ✅
- full flow：submit → approve → list → check-ok → check-out-of-window
- reject → 之后 approve 应 409
- 参数校验：polygon<3、end<start

---

## 2. GeoFence Engine · v1.0 UTM

### 后端
| 文件 | 用途 |
|---|---|
| `app/services/geofence.py` | 静态 zone 注册表 + 射线法 point-in-polygon |
| `app/api/v1/geofence.py` | 2 endpoint REST |

### 内置 seed（4 zones · 3 kinds）
| ID | 名称 | 种类 |
|---|---|---|
| `bj-tiananmen` | 北京天安门核心禁飞区 | `no_fly` |
| `bj-capital-airport` | 首都机场净空区 | `no_fly` |
| `cd-shuangliu-airport` | 双流机场净空区 | `no_fly` |
| `bj-height-120` | 北京城区默认限高 120m | `height` |

支持环境变量 `GEOFENCE_ZONES_FILE=path/to/zones.json` 加载生产 zone 库。

### REST endpoint
| 方法 | 路径 | 功能 |
|---|---|---|
| GET  | `/api/v1/geofence/zones` | 列出全部 zone |
| POST | `/api/v1/geofence/check` | 输入航点数组 → 返回 `{ok, violations[]}` |

### 违规检测
- `no_fly` → 硬拦截
- `restricted` → 警告 + 需特批
- `height` → 对比 alt vs zone.max_alt_m

### 测试
`tests/test_geofence.py` · 3 case ✅
- 列表 + 远离所有 zone 的航点通过
- 天安门内 no_fly 检出
- 限高区 200m 检出、80m 通过

---

## 3. Audit Middleware · v1.0 等保

### 后端
| 文件 | 用途 |
|---|---|
| `app/services/audit_middleware.py` | Starlette BaseHTTPMiddleware |

### 拦截规则
- **拦**：所有 POST / PUT / PATCH / DELETE
- **不拦**：GET / HEAD / OPTIONS / `/health` / `/ws/*`

### 记录字段
| 字段 | 来源 |
|---|---|
| `actor_id` | Bearer JWT `sub`（可空 → 匿名） |
| `action` | `{METHOD} {path}` |
| `resource` | request.url.path |
| `diff.status_code` | 响应状态码 |
| `diff.duration_ms` | 处理耗时 |
| `diff.query` | query params |
| `ip` | request.client.host |
| `ua` | User-Agent |
| `ts` | unix 秒 |

### 三级落地策略
1. **测试** → `app.state.audit_sink = InMemoryAuditSink()` （env `AUDIT_MEMORY_SINK=true`）
2. **生产** → `app.state.async_sessionmaker` 存 `audit_logs` 表
3. **兜底** → 结构化 JSON 日志（`logger.info("AUDIT ...")`）

### 环境开关
- `ENABLE_AUDIT_MIDDLEWARE=true` （默认开）
- 静默失败：审计写库任何异常都不会影响主请求

### 测试
`tests/test_audit_middleware.py` · 2 case ✅
- GET `/geofence/zones` 不落库；POST `/geofence/check` 落库
- UOM submit + approve 全流程都被审计

---

## 4. 前端集成

### 新增组件 `components/UOMPanel.tsx`
- 顶部右上角按钮 「🛡 飞行报备」
- 点开弹出 Modal（860px），包含：
  - **表单**：运营人ID · 飞手 · 机身注册号 · 作业性质 · 限高 · 时段（RangePicker）
  - **默认区域**：如果任务编辑器里已经画了 ≥3 点，自动用当前 mission 多边形
  - **列表**：全部报备表格，pending 行显示「批准/驳回」按钮
- 打开 Modal 时每 3s 自动 poll（能实时看到 auto-approver 生效）

### 前端布局最终形态
```
┌──────────────────────────────────────────────────────────┐
│    [🎯 跟随]                                [🛡 飞行报备]   │
│  ┌──────────┐                          ┌───────────────┐│
│  │🎮 SIM控制│      Cesium 3D           │✏️ 任务编辑     ││
│  │  mission │       🚁 D1 (3D)         │  绘制/派发    ││
│  │  3/3 ✅  │       🟠 尾迹            │┌─────────────┐││
│  └──────────┘                          ││📅 历史轨迹  │││
│                                        │└─────────────┘││
│                                        └───────────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## 5. 端到端 verify

```
═══ GeoFence zones ═══
  4 zones

═══ GeoFence check inside 天安门 no-fly ═══
  ok=False, violations=1
    - no_fly: waypoint 0 落入禁飞区 北京天安门核心禁飞区

═══ UOM submit + auto-approve ═══
  submitted rid=a0dc4cb9, status=pending
  t=4s ✅ approved by auto-uom-mock, code=UOM-1783647788-a0dc4cb9

═══ UOM check ready-for-takeoff ═══
  ok=True, reason=ok

═══ Live page has UOMPanel ═══
  page: 6689B, status=200
```

---

## 6. 测试统计
```
Backend total:  58 pass / 1 skip
新增 case:     +8
  · test_uom.py               3
  · test_geofence.py          3
  · test_audit_middleware.py  2
Frontend tsc: 0 error
```

---

## 7. 累计能力

| 版本 | 里程碑 |
|---|---|
| v0.1 | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| **v2.0 Compliance ①** | **UOM 报备 + GeoFence 围栏 + Audit 全审计** |

---

## 8. 遗留 / 下一步（仍限 v2.0 · 非 AI/非 3D）

- [ ] 把 GeoFence violations 挂进 mission_dispatcher，派发前**硬拦截**（当前只提供 API，未接主任务流）
- [ ] UOM `check_ready_for_takeoff` 接进 `dispatchMission`，无 approved 报备时 409
- [ ] 前端 CesiumMap 把 no_fly 多边形**画出来**（红色半透明填充）
- [ ] Audit logs 生产落库：把 `async_sessionmaker` 挂到 `app.state` 上，切换到真 postgres 就自动生效
- [ ] Prometheus `/metrics` endpoint（v1.0 监控条）
- [ ] `docker-compose.prod.yml` profile（v0.5 部署条）

🐈 v2.0 第一根桩已打入。
