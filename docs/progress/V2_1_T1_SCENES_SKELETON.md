# V2.1 T1 · 3DGS Reality Studio 骨架落地

**日期**：2026-07-13
**主线**：v2.1 T1 · 三维扫描 Reality Studio（v2.0 合规冲刺收官后首桩）
**状态**：✅ 数据库表 + 状态机 + 8 endpoints + 前端场景管理页 + 13 新测试全绿

---

## 🎯 v2.1 T1 定位

**为什么先做 3DGS？** — 这是 SkyMaster 相对大疆司空 2 的**核心差异化壁垒**：
- 司空 2：仅提供 2D 正射拼图（Pix4D/DJI Terra 处理链）
- SkyMaster：无人机采集 → COLMAP 结构还原 → 3D Gaussian Splatting 训练 → 可漫游 3D 场景

政务/应急/测绘/文物客户核心需求。

---

## 🚫 本轮不做（明确边界）

- ❌ 真训练器接入（COLMAP + gsplat 编译栈） · 放 T1.5
- ❌ 大文件分片上传 · 放 T1.2
- ❌ 3D 前端 viewer（three.js + splat-viewer） · 放 T1.3

**本轮聚焦**：接口稳定 · 数据库落表 · 状态机守恒 · 授权门槛 · 前端可点。

---

## 📦 交付物

### 1. `models/scene.py` · Scene + SceneAsset ORM（+180 行）

**Scene 表**：
- 主键 + org/owner/mission FK
- 9 态状态机字段 `status`：draft / ingesting / ingested / colmap / colmap_done / training / ready / failed / archived
- 摘要指标：n_source_images / n_points / n_gaussians / psnr_train
- error_msg 存流水线错误 · coord_system 存坐标系 · meta JSONB 存扩展

**SceneAsset 表**：
- FK 到 scenes（cascade delete）
- 资源类型：source_image / source_video / colmap_sparse / colmap_dense / gsplat_ckpt / gsplat_ply / preview_thumb / log
- sha256_hex + size_bytes（去重 + 完整性）

### 2. `alembic/versions/20260713_0019_scenes.py` · 迁移（+70 行）

两表 + 全套索引（org/owner/mission/status/scene/kind）· 完整 downgrade

### 3. `services/scene_pipeline.py` · 状态机 + Executor 抽象（+180 行）

**核心不变式** — `_LEGAL_TRANSITIONS` 硬编码合法转移：
```
draft → ingesting → ingested → colmap → colmap_done → training → ready
   │        │           │         │          │             │        │
   └────────┴───────────┴─────────┴──────────┴─────────────┴────►failed
                                                                  │
   archived (terminal, only forward)     failed → {draft, archived}
```

**`Executor` 抽象基类**：
- `run_colmap(scene_id) → ExecResult`
- `run_training(scene_id) → ExecResult`
- `NoOpExecutor` 默认（生成假数据 · dev/test）
- 未来 `ColmapExecutor` / `GsplatExecutor` / `QueueExecutor` 直接替换

**Pipeline orchestrator**：
- `start_colmap` · ingested → colmap → (成功 colmap_done + 记录 n_points) 或 (失败 failed)
- `start_training` · colmap_done → training → (成功 ready + 记录 n_gaussians/psnr) 或 (失败 failed)

### 4. `api/v1/scenes.py` · 8 endpoints（+270 行）

| Method | Endpoint | 用途 |
|--------|----------|------|
| POST | `/scenes` | 创建 draft 场景 |
| GET  | `/scenes` | 列表（org-scoped，可 status 过滤） |
| GET  | `/scenes/{id}` | 详情 + assets |
| PATCH | `/scenes/{id}` | 改 name/description/coord_system |
| POST | `/scenes/{id}/ingest` | draft → ingested |
| POST | `/scenes/{id}/colmap` | ingested → colmap_done |
| POST | `/scenes/{id}/train` | colmap_done → ready |
| POST | `/scenes/{id}/reset` | failed → draft |
| POST | `/scenes/{id}/archive` | 任意态 → archived |

**授权分层**：
- `_authz_read`：admin OR 同 org OR 场景 owner
- `_authz_write`：admin OR 场景 owner OR 同 org 且 role=system_officer

### 5. `api/v1/router.py` · 路由注册（+1 行）

### 6. 前端 `app/dashboard/scenes/page.tsx` · 场景管理主页（+300 行）

**列表卡**：
- Table 列：名称 / 状态 Tag / 源图数 / 点数 / Gaussians / PSNR / 操作按钮组
- **智能操作按钮**：根据 status 动态显示对应下一步操作
  - draft → 「开始摄入」按钮
  - ingested → 「运行 COLMAP」按钮
  - colmap_done → 「训练 3DGS」按钮
  - failed → 「重置」按钮
  - 任意非归档 → 「归档」（Popconfirm）
- **展开行**：Steps 组件展示 4 步流水线进度 · failed 显示红色 Alert + 错误信息 · Descriptions 展示元数据

**新建场景 Modal**：Form 表单 · name/description/coord_system

### 7. 前端 `lib/api.ts` · 类型 + 5 函数（+70 行）

- `SceneStatus / Scene / SceneAsset / ScenesList / SceneCreate` 严格对齐后端
- `listScenes / getScene / createScene / sceneAction` 4 函数

### 8. Dashboard 导航接入（`layout.tsx` +2 行）

「3DGS 场景」菜单项 · `ThunderboltOutlined` 图标 · 位于「CIIO 自评」之后。

### 9. 测试 `tests/test_scene_pipeline.py` · 13 新测试（+180 行）

| 测试 | 覆盖 |
|------|------|
| `test_legal_transitions_happy_path` | draft→...→ready 直通链全部合法 |
| `test_terminal_states_reject_further_transitions` | archived 只入不出 · ready 只到 archived |
| `test_illegal_transitions_are_blocked` | 跨阶段跳跃全部被拦 |
| `test_failed_can_reset_or_archive` | failed 只能到 draft/archived |
| `test_transition_rejects_illegal_move` | InvalidTransition 异常 |
| `test_transition_clears_error_on_recovery` | failed→draft 清空 error_msg |
| `test_transition_records_error_on_failed` | 失败时记录 error_msg |
| `test_start_colmap_success_advances_and_records_metrics` | 成功路径 + 摘要指标 |
| `test_start_colmap_failure_transitions_to_failed` | 失败路径回落 failed |
| `test_start_training_success_records_gaussians_and_psnr` | 训练成功记录 gaussians + psnr |
| `test_start_training_from_wrong_state_raises` | 强制守恒 |
| `test_noop_executor_is_default_and_succeeds` | 默认 executor 可用 |
| `test_all_states_are_valid_enum` | 状态机每个 state 都在 SCENE_STATUSES 内 |

**执行结果**：
```
tests/test_scene_pipeline.py .............   [ 39%]
tests/test_ciio_assessment.py ........       [ 63%]
tests/test_audit_export.py .......           [ 84%]
tests/test_sm2_rotation.py .....             [100%]
============================== 33 passed in 0.18s ==============================
```

---

## ✅ 完整验证

- 新测试 · 13/13 全绿
- v2.0 合规回归测试（R21+R22+R23）· 20/20 全绿
- 累计 33 测试全绿
- TypeScript tsc --noEmit exit=0

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/models/scene.py                          (+180 行 · 新增)
├── alembic/versions/20260713_0019_scenes.py     (+70 行 · 新增)
├── app/services/scene_pipeline.py               (+180 行 · 新增)
├── app/api/v1/scenes.py                         (+270 行 · 新增)
├── app/api/v1/router.py                         (+2 行 · 注册)
└── tests/test_scene_pipeline.py                 (+180 行 · 新增, 13 tests)

frontend-v0.1/
├── lib/api.ts                                   (+70 行 · Scene 类型+5函数)
├── app/dashboard/scenes/page.tsx                (+300 行 · 新增)
└── app/dashboard/layout.tsx                     (+2 行 · 菜单+图标)
```

**代码规模** · +1254 行（后端 882 + 前端 372）

---

## 📝 v2.1 T1 后续路线

| 环节 | 状态 | 预计工时 |
|------|------|---------|
| **T1.0 骨架**（本轮） | ✅ 完成 | 2-3h |
| T1.1 上传接口（分片+断点续传） | ⏳ 下轮 | 3-4h |
| T1.2 COLMAP 实执行器（Docker 化） | ⏳ | 4-6h |
| T1.3 gsplat 实训练器（Docker + CUDA） | ⏳ | 6-8h |
| T1.4 3D viewer 前端（three.js + splat） | ⏳ | 4-6h |
| T1.5 场景商店/共享 | ⏳ v2.1 后段 | — |

**推荐先做 T1.1 上传接口** · 因为没上传就没数据，其他 executor 都是空转。

---

**T1.0 状态** · ✅ 完成
**推进节奏** · v2.0 合规收官后立即进入 v2.1，无中断
