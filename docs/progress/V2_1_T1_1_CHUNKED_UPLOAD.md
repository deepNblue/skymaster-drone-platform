# V2.1 T1.1 · 场景资源分片上传

**日期**：2026-07-13
**主线**：v2.1 T1.1 · 大文件分片上传 + SHA-256 去重 + 断点续传
**状态**：✅ 存储抽象 + 5 endpoints + 前端上传器 + 12 新测试全绿，累计 45/45

---

## 🎯 T1.1 目标

**核心问题**：无人机采集单场景 500-3000 张 24MP 图像，单文件 8-15MB，累计 4-45GB。整传必然失败：
- 浏览器内存爆
- 网络中断 → 从头重来
- 相同文件多次上传 → 存储爆

**解决方案**：内容寻址存储（CAS）+ 分片 + SHA-256 校验 + 断点续传 + 自动去重

---

## 📦 交付物

### 1. `services/object_storage.py` · 存储抽象（+230 行）

**`StorageBackend` 抽象基类** · 4 个抽象方法：
- `stage_chunk(upload_id, idx, data)` · 落分片
- `list_chunks(upload_id) → [idx]` · 断点续传探测
- `assemble(upload_id, expected_sha256, total_chunks) → ObjectRef` · 拼装 + 校验 + CAS 入库
- `open_read / size / delete_staging` · 常规操作

**`LocalFSBackend`（开发默认）** · 三层目录：
```
{root}/
├── staging/{upload_id}/{000000..}.chunk    ← 未拼装的分片
└── cas/{sha[:2]}/{sha[2:]}                  ← 内容寻址落地文件
```

**核心不变式**：
- 分片 `.tmp` → `os.replace` 原子写入
- 拼装边流边计算 SHA-256，末尾比对，不匹配则删除 `.tmp` 抛 `StorageIntegrityError`
- 已存在的 CAS 条目 → **paranoid 校验**（`_sha256_file`），防止磁盘位翻转
- 路径组件 `_safe_component` 拒绝 `../` `\` `\x00`，杜绝目录穿越

**未来扩展**：S3Backend / MinIOBackend / AliyunOSSBackend 只需实现 4 方法。

### 2. `api/v1/scenes_upload.py` · 5 endpoints（+220 行）

| Method | Endpoint | 用途 |
|--------|----------|------|
| POST   | `/scenes/{sid}/uploads` | 起上传（声明文件名 + sha256 + size + chunks）|
| PUT    | `/scenes/{sid}/uploads/{uid}/chunks/{idx}` | 传单个分片 |
| GET    | `/scenes/{sid}/uploads/{uid}` | 查已到达分片（断点续传） |
| POST   | `/scenes/{sid}/uploads/{uid}/complete` | 拼装 + 写 SceneAsset 行 |
| DELETE | `/scenes/{sid}/uploads/{uid}` | 中止（GC staging） |

**限流硬顶**：
- 单分片 ≤ 32 MiB（防内存爆）
- 单文件 ≤ 64 GiB（防误上传）
- 单文件 ≤ 100k 分片（防恶意分片攻击）

**去重语义**：同 SHA-256 二次上传 → CAS 命中，磁盘零占用，但新 SceneAsset 行仍写入（每场景都能看到自己的引用）。响应中 `dedup: true` 提示前端。

**授权**：复用 scenes.py 的 `_authz_write` · 上传归属仅 owner 或 admin 可续/查/complete。

### 3. `api/v1/router.py` · +1 行

### 4. 前端 `lib/api.ts` · 上传工具（+110 行）

**`sha256File(file)`** · 用浏览器原生 Web Crypto API 计算 SHA-256（无第三方依赖）

**`uploadFile(sceneId, file, kind, onProgress)`** · 高层封装：
1. 计算 SHA-256
2. `uploadStart` 声明元数据
3. 断点续传：从 `received_chunks` 跳过已到达的
4. 循环 `uploadChunk` 4MiB 一片，每片回调 `onProgress`
5. `uploadComplete` 拼装 + 返回 asset_id + dedup 标志

### 5. 前端 `/dashboard/scenes/[id]/page.tsx` · 场景详情页（+280 行）

**流水线进度卡**：4 步 Steps · failed 显示红色 Alert + 重置按钮 · 根据 status 显示对应下一步操作按钮

**四指标卡**：源图/SfM 点数/高斯数/PSNR

**上传卡**（仅 draft/ingesting 状态显示）：
- Ant Dragger 拖拽上传，多文件批量
- 上传队列表：文件名 + Progress 条 + 状态 Tag（上传中/已入库/去重命中/失败）
- 拖 100 张图会自动排队 · 网络断了刷新页面继续传

**资源列表卡**：显示所有 SceneAsset · 文件名 / kind / 大小（KB/MB/GB 智能显示）/ SHA-256 前 16 字符

### 6. 测试 `tests/test_object_storage.py` · 12 新测试（+150 行）

| 测试 | 覆盖 |
|------|------|
| `test_safe_component_blocks_traversal` | `../` 目录穿越攻击被拦 |
| `test_stage_and_list_chunks` | 乱序分片正确排序 |
| `test_stage_chunk_rejects_out_of_range` | 负/过大 idx 被拒 |
| `test_assemble_happy_path_two_chunks` | 两分片拼装 + SHA 匹配 |
| `test_assemble_missing_chunk_raises` | 缺片明确报错 |
| `test_assemble_integrity_mismatch_raises` | SHA 不匹配 → 删 .tmp + 抛 |
| `test_assemble_dedup_returns_existing` | 去重命中 mtime 不变 |
| `test_open_read_and_size` | 读写对称 |
| `test_delete_staging_is_idempotent` | 二次 delete 不炸 |
| **`test_assemble_detects_corrupted_cas_entry`** | 磁盘 CAS 被篡改 → paranoid 校验发现 |
| `test_cas_path_rejects_bad_sha` | 坏 SHA 被拒 |
| `test_large_multipart_assembly` | 5×4KB 随机数据端到端 |

**执行结果**：
```
tests/test_object_storage.py ............   [ 26%]
tests/test_scene_pipeline.py .............  [ 55%]
tests/test_ciio_assessment.py ........      [ 73%]
tests/test_audit_export.py .......          [ 88%]
tests/test_sm2_rotation.py .....            [100%]
============================== 45 passed in 0.19s ==============================
```

---

## ✅ 完整验证

- 新测试 · 12/12 全绿
- 全项目累计 · 45/45 全绿
- TypeScript tsc --noEmit exit=0
- 5 新 endpoints + 前端上传器 + 详情页 · 端到端可点

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/services/object_storage.py         (+230 行 · 新增)
├── app/api/v1/scenes_upload.py            (+220 行 · 新增)
├── app/api/v1/router.py                   (+2 行 · 注册)
└── tests/test_object_storage.py           (+150 行 · 新增, 12 tests)

frontend-v0.1/
├── lib/api.ts                             (+110 行 · 上传工具+Web Crypto SHA256)
└── app/dashboard/scenes/[id]/page.tsx     (+280 行 · 新增·详情页)
```

**代码规模** · +992 行（后端 602 + 前端 390）

---

## 📝 v2.1 T1 后续路线

| 环节 | 状态 |
|------|------|
| T1.0 骨架 | ✅ 完成 |
| **T1.1 上传** | ✅ 完成（本轮） |
| T1.2 COLMAP 实执行器（Docker 化） | ⏳ 下轮 · 4-6h |
| T1.3 gsplat 实训练器（Docker + CUDA） | ⏳ · 6-8h |
| T1.4 3D viewer 前端（three.js + splat） | ⏳ · 4-6h |
| T1.5 场景商店/共享 | ⏳ · v2.1 后段 |

**T1.2 优先级**：Docker 化 COLMAP `ColmapExecutor(Executor)` 类，替换 NoOpExecutor 即可跑真 SfM。因为 `Executor` 抽象已就绪，业务代码零改动。

---

**T1.1 状态** · ✅ 完成
**推进节奏** · v2.0 收官+v2.1 T1.0+T1.1 三连击不中断
