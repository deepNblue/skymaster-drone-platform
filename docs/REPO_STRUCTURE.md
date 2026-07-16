# SkyMaster 仓库结构说明

**创建日期**：2026-07-16
**背景**：v2.0 交付完成后梳理仓库结构，为 v2.1 收敛做准备。

---

## 一、双目录并存的历史成因

仓库中同时存在两组后端 + 前端目录：

```
skymaster-drone-platform/
├── backend/          ← v1.x legacy (14 725 行)
├── backend-v0.1/     ← v2.x 主线 (52 579 行)
├── frontend/         ← v1.x legacy (1 472 行)
├── frontend-v0.1/    ← v2.x 主线 (20 783 行)
├── docs/             ← 共享文档
└── .github/          ← 共享 CI
```

**"v0.1" 后缀 ≠ 版本号 0.1**。这是 2026-06 v2.0 大版本重构时的目录后缀，本意是"下一代 backend"，语义上应该读作 `backend-next`。命名沿用至今造成混淆。

---

## 二、当前分工（截至 2026-07-16）

### `backend/` 与 `frontend/` — v1.x Legacy

**内容**：
- `backend/api/v1/main.py` — v1.0 (基础 CRUD) + v1.1 (AI 路径规划、自动避障) 的 FastAPI 主入口
- `backend/core/` — MAVLink 桥接、任务规划器
- `backend/api/v1/planning.py` — A* / RRT* / RRT-Connect 路径规划
- `backend/api/v1/safety.py` — 地理围栏、避障、返航
- `backend/tests/` — v1.x 单元测试 + v2.0 新增 **100 机压测框架**

**代际归属**：v1.0 → v1.1

**当前状态**：
- ❌ **不再新增功能**
- ✅ 可修 bug、可加压测
- ✅ v2.0 新增的 100 机压测框架挂在这里（因为压测的是 v1.1 的 `WebSocketManager`）

**Git 活动**（v2.0 阶段 2026-06-01 起）：13 次改动（主要是 T9.3-T9.5 压测优化）

### `backend-v0.1/` 与 `frontend-v0.1/` — v2.x 主线

**内容**：
- `backend-v0.1/app/` — v2.0 六大模块完整实现（3 591 py 文件）
- `backend-v0.1/alembic/` — 数据库迁移
- `backend-v0.1/tests/` — v2.0 测试（含 UAT 端到端演练）
- `frontend-v0.1/` — v2.0 前端（80 个 TS/TSX 组件）

**代际归属**：v2.0 → v2.1 → v2.2 ...

**当前状态**：
- ✅ **v2.0 六大模块 MVP 全绿**（见 `V2.0_DELIVERY_REPORT.md`）
- ✅ v2.1 三条工作线基础（Track D/E/F，见 `V2.1_KICKOFF.md`）

**Git 活动**（v2.0 阶段）：128 次后端 + 95 次前端 = **223 次改动**（绝对主线）

---

## 三、为什么 100 机压测挂在 `backend/` 而不是 `backend-v0.1/`

**压测对象决定归属**：
- 场景 A/B/C 用到的 `WebSocketManager` 存在于 `backend/api/v1/main.py`（v1.1 引入）
- `backend-v0.1/` 的 v2.0 架构走 SSE + Redis Pub/Sub，不再用 v1.1 的 `WebSocketManager`
- 因此压测框架必然挂在 `backend/`

**当 v2.0 主线遥测走向定型后**（预计 v2.1），需要为 `backend-v0.1/` 单独开一套压测（复用同一批 `mock_drone.py`）。

---

## 四、收敛路线（v2.1 计划）

### 阶段 1 · 文档化（当前，本文档）✅

- 明确 `backend/` = v1.x legacy，`backend-v0.1/` = v2.x 主线
- 更新根 `README.md` 指向本说明

### 阶段 2 · 归档（v2.1 中期）

**方案 A（推荐）· 移入 legacy/ 目录**：

```
legacy/
├── backend-v1/       ← 从 backend/ 迁移
└── frontend-v1/      ← 从 frontend/ 迁移

backend/              ← 从 backend-v0.1/ 重命名而来
frontend/             ← 从 frontend-v0.1/ 重命名而来
```

**风险**：
- 需修改 ~50 处 import / Dockerfile / CI 路径引用
- 100 机压测框架需拆分（`WebSocketManager` 相关跟随迁移到 legacy）

**执行方式**：subagent 完成，全量测试通过后合并

**方案 B · 保持现状 + 明确标注**：

- 只在 `backend/README.md` 加 "此目录为 v1.x legacy，请去 backend-v0.1/" 头部提示
- 优点：0 风险，无需改 import
- 缺点：新开发者仍需绕道

### 阶段 3 · 双目录合并（v2.2+）

- 若 v1.x AI 路径规划功能已被 v2.x 完全覆盖，可彻底删除 legacy/
- 若尚未覆盖，把 legacy 中的 planning/safety 模块迁移到 backend-v0.1/app/services/

---

## 五、给新开发者的建议

**如果你要**：

| 场景 | 去哪里 |
|------|--------|
| 新增 v2.x 功能（业务逻辑） | `backend-v0.1/app/` |
| 新增 v2.x API | `backend-v0.1/app/api/` |
| 新增 v2.x 前端组件 | `frontend-v0.1/src/` |
| 修 v1.x AI 路径规划 bug | `backend/api/v1/planning.py` |
| 新增 v1.x MAVLink 压测 | `backend/tests/load/` |
| 新增 v2.x 集成测试 | `backend-v0.1/tests/` |
| 编辑共享文档 | `docs/` |
| 修 CI workflow | `.github/workflows/` |

**不确定去哪里？** 看这个决策树：

```
新功能是 v2.0 六大模块之一（报备/3DGS/Vision/Copilot/Community/Marketplace）?
  YES → backend-v0.1/ + frontend-v0.1/
  NO  → 是否与 MAVLink/无人机通信底层相关?
    YES → backend/ (v1.x legacy, 慎重)
    NO  → 找架构师确认归属
```

---

## 六、v2.0 阶段验证

**v2.0 六大模块全部在 `backend-v0.1/` 中实现**：

- ✅ 飞行报备审批 → `backend-v0.1/app/api/v1/approvals*`
- ✅ Reality Studio → `backend-v0.1/app/api/v1/scenes*` + `services/scene_ingestion.py`
- ✅ Vision AI → `backend-v0.1/app/services/vision_*`
- ✅ Copilot Agent → `backend-v0.1/app/services/copilot*`
- ✅ Community → `backend-v0.1/app/api/v1/community*`
- ✅ Model Marketplace → `backend-v0.1/app/api/v1/marketplace*`

`backend/` 中**没有任何 v2.0 六大模块相关代码**，纯粹是 v1.x 遗留。

---

## 七、当前技术债汇总

| # | 债务 | 影响 | 优先级 |
|---|------|------|-------|
| 1 | 双目录命名混淆 | 新人上手困难 | P1 |
| 2 | `backend/` 与 `backend-v0.1/` 有重复的 `__init__.py`、`requirements.txt` | 环境管理混乱 | P2 |
| 3 | 100 机压测未纳入 backend-v0.1 | v2.x 遥测通路未覆盖 | P1（v2.1 补） |
| 4 | 只有场景 A 进 CI | B/C/D 手动跑 | P2（v2.1 补） |
| 5 | UOM 生产账号缺失 | T7.2 阻塞 | P0（商务） |

---

## 八、结语

**双目录不是缺陷，而是重构过渡态。** v2.0 阶段用这种"新旧并存"的方式避免了停机重构，实现了 73 362 行代码的平滑落地。

**v2.1 阶段的目标是把过渡态收敛为"legacy + 主线"的清晰二元结构。**

🐈
