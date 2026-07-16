# V2.1 T1.3 · 训练产物导出与下载

**日期**：2026-07-13
**主线**：v2.1 T1.3 · 政务客户桌面 GS viewer 关键交付物
**状态**：✅ 4 endpoints + 前端产物区 + 15 新测试全绿，累计 80/80

---

## 🎯 T1.3 定位

**T1.2 兑现**：GsplatExecutor 训练完成会得到 `.ply` 文件。
**T1.3 交付**：让客户能**下载**这些 `.ply/.splat`，拉进桌面 viewer 漫游。

**为什么这是政务/测绘客户核心**：
- SuperSplat（在线）+ Postshot（本地）都支持拖拽 `.ply`
- 客户不想在浏览器里看，想拿到本地存档、给上级演示、做二次剪辑
- 无下载功能 = 3DGS 数据锁死在平台里，客户不接受

---

## 📦 交付物

### 1. `api/v1/scenes_artifacts.py` · 4 endpoints（+270 行）

| Method | Endpoint | 用途 |
|--------|----------|------|
| POST | `/scenes/{sid}/artifacts/register` | worker 上报生成的 `.ply` 到 SceneAsset 表 |
| GET | `/scenes/{sid}/artifacts` | 列表所有下载产物（过滤掉源图） |
| GET | `/scenes/{sid}/artifacts/manifest.json` | JSON 清单（3D viewer 引导） |
| GET | `/scenes/{sid}/assets/{aid}/download` | 流式下载单个资产 |

**四个纯函数（可测）**：

- **`_rfc6266_disposition(filename)`** · Unicode 安全的 Content-Disposition
  - ASCII fallback: `filename="scene.ply"` 兼容旧浏览器
  - RFC 5987: `filename*=UTF-8''场景1.ply%22` 用户看到中文
  - 硬防御：`/` `\` `\r` `\n` `\x00` 全被替换为 `_`（防 header 注入 / 目录穿越）

- **`_guess_content_type(filename)`** · `.ply` / `.splat` 特化为 `application/octet-stream`（mimetypes db 里没有）

- **`_filter_artifacts(assets)`** · 只保留 `gsplat_ply / gsplat_ckpt / colmap_sparse / preview_thumb` 四类，源图/日志被排除

- **`_asset_to_artifact(sid, a)`** · DB row → DTO 附带 `download_url`

**流式下载**：
- 从 `object_storage.open_read(ref)` 拿文件句柄
- 1MiB/chunk 迭代器 · `finally: fh.close()` 保证句柄泄漏零
- `Content-Length` + `X-Sha256` header · 客户端可自验完整性

**授权**：
- 下载走 `_authz_read`（scene 可见性），一般 org 成员即可下载
- 注册走 `_authz_write`（scene owner / admin / same-org system_officer）

**关键安全防御**：文件从 `storage_path` 读，不解析 URL 参数指定路径 · **绝对不可能通过 URL 参数下载任意文件**。

### 2. `api/v1/router.py` · +2 行注册

### 3. 前端 `lib/api.ts` · +45 行 TypeScript 类型 + 3 函数

- `Artifact / ArtifactList / ArtifactManifest` 严格类型
- `listArtifacts / artifactManifest / artifactDownloadUrl` 3 函数

### 4. 前端 `/dashboard/scenes/[id]/page.tsx` · 训练产物区（+55 行）

**仅在 `status ∈ {ready, archived}` 时加载**，避免无用请求：
- 蓝色 Alert 说明推荐桌面 viewer（SuperSplat 在线 · Postshot 本地）
- Table：文件名 / 类型 Tag / 大小智能显示（KB/MB/GB）/ 下载按钮
- 下载走原生 `<a href target=_blank>`，浏览器接管、支持大文件流式

---

### 5. 测试 `tests/test_scenes_artifacts.py` · 15 新测试（+140 行）

| 测试组 | 覆盖 |
|--------|------|
| **Disposition 4 tests** | ASCII / Unicode 中文 / `../` 穿越 / CRLF 注入 |
| **Content-Type 4 tests** | `.ply` / `.splat` / `.zip` / 未知扩展名 |
| **Filter 2 tests** | 只留输出类 / 空表 |
| **DTO 2 tests** | download_url 拼接 / 双向映射 |
| **模式一致性 1 test** | ARTIFACT_KINDS ⊆ SCENE_ASSET_KINDS |
| **边界 2 tests** | 多点扩展名 / null byte 拒绝 |

**Disposition CJK 测试**特别有价值 — RFC 5987 percent-encoding 保证客户命名"场景1.ply" 下载后仍是中文文件名（而不是 ` 场景1 ` mojibake）。

**null byte 迭代**：首轮实现漏了 `\x00`（`.replace("\x00", "_")`），测试立即抓到 · 补丁 3 行改动。

**执行结果**：
```
tests/test_scenes_artifacts.py ...............     [ 18%]
tests/test_scene_executors.py ....................  [ 43%]
tests/test_object_storage.py ............           [ 58%]
tests/test_scene_pipeline.py .............          [ 75%]
tests/test_ciio_assessment.py ........              [ 85%]
tests/test_audit_export.py .......                  [ 93%]
tests/test_sm2_rotation.py .....                    [100%]
============================== 80 passed in 0.61s ==============================
```

---

## ✅ 完整验证

- 新测试 · 15/15 全绿
- 全项目累计 · **80/80** 全绿
- 80 = 15 (T1.3) + 20 (T1.2) + 12 (T1.1) + 13 (T1.0) + 20 (v2.0 R21+R22+R23)
- TypeScript tsc --noEmit exit=0
- 运行时长 · 0.61s

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/api/v1/scenes_artifacts.py    (+270 行 · 新增)
├── app/api/v1/router.py              (+2 行)
└── tests/test_scenes_artifacts.py    (+140 行 · 新增, 15 tests)

frontend-v0.1/
├── lib/api.ts                        (+45 行 · Artifact 类型+3 函数)
└── app/dashboard/scenes/[id]/page.tsx (+55 行 · 产物区+load 时机)
```

**代码规模** · +512 行（后端 412 + 前端 100）

---

## 🔑 端到端流程（已闭合）

```
1. 前端 uploadFile()        ← T1.1
2. 后端 chunk assemble → CAS ← T1.1
3. POST /scenes/{sid}/ingest ← T1.0
4. POST /scenes/{sid}/colmap ← T1.0 → GsplatExecutor.run_colmap ← T1.2
5. POST /scenes/{sid}/train  ← T1.0 → GsplatExecutor.run_training ← T1.2
6. Worker 调 POST /scenes/{sid}/artifacts/register  ← T1.3
7. GET /scenes/{sid}/artifacts → 前端表格 → 下载 .ply  ← T1.3
8. 客户拖 .ply 进 SuperSplat/Postshot 漫游 3D 场景
```

**T1.0 状态机 + T1.1 上传 + T1.2 执行器 + T1.3 下载** = 一条完整的 photogrammetry-as-a-service 交付链。

---

## 📝 v2.1 T1 路线更新

| 环节 | 状态 |
|------|------|
| T1.0 骨架 | ✅ 完成 |
| T1.1 上传 | ✅ 完成 |
| T1.2 真执行器 | ✅ 完成 |
| **T1.3 产物导出** | ✅ 完成（本轮） |
| T1.4 3D viewer（three.js + splat 内嵌） | ⏳ 下轮 · 4-6h |
| T1.5 Docker 镜像 CI 与生产部署 | ⏳ v2.1 后段 |

**T1.4 优先级**：客户能在线预览再决定下载 · 减少大文件下载时间浪费 · 也是差异化竞争点（司空 2 完全没有内嵌 3D 交互）。

---

**T1.3 状态** · ✅ 完成
**五连击** · v2.0 R23 收官 → T1.0 → T1.1 → T1.2 → T1.3 · 累计 80 tests 全绿
