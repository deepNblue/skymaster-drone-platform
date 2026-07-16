# V2.1 T1.4 · 内嵌 3D 点云 viewer

**日期**：2026-07-13
**主线**：v2.1 T1.4 · three.js + 手写 PLY 解析器 · 客户在线预览
**状态**：✅ 独立 PLY parser + PointCloudViewer + 14 前端测试全绿 · 后端 80 tests 保持全绿

---

## 🎯 T1.4 定位

**T1.3 交付**：客户能下载 `.ply`。
**T1.4 交付**：客户**在线预览**是不是自己想要的场景，再决定要不要下载 4GB 大文件。

**差异化立论**：
- 大疆司空 2 完全没有内嵌 3D 交互
- 阿里云海外看 3DGS 需要跳到独立子域名，中断作业流
- SkyMaster 直接嵌在场景详情页里，业务流不中断

---

## 🚫 明确不做（本轮边界）

- ❌ 完整 Gaussian Splatting 光栅化（需 splat rasterizer，~500KB dep + WebGL 复杂着色器） — 放 T1.5
- ❌ 处理 200MB+ 大文件预览 — 客户端硬顶，超限只提示下载到桌面 viewer
- ❌ VR/AR 模式 — v2.2 空间智能路线里做

**本轮聚焦**：**点云预览**已经足够回答 "是不是我要的场景" 这个问题（COLMAP sparse + 训练前几步都是点云）。

---

## 📦 交付物

### 1. `frontend-v0.1/lib/ply-parser.ts` · 手写 PLY 解析器（+280 行）

**为什么手写而不是用现成库**：
- three.js 官方 PLYLoader 需要 DOM/网络请求，不能用纯 ArrayBuffer 测试
- `@mkkellogg/gaussian-splats-3d` 依赖巨大（~500KB gzipped）且只处理 3DGS 特化格式
- **手写**给了完全的可测性 + 3DGS 兼容性

**关键设计**：
- 纯函数 · 无 DOM · 无 three.js · 无 fetch
- 支持 **binary_little_endian / binary_big_endian / ascii** 三种 PLY 格式
- **跳过 3DGS 特化属性** · nerfstudio 输出的 PLY 每顶点有 17+ 个 float（f_dc_*, scale_*, rot_*, opacity, …），我们只读 x/y/z + 可选 red/green/blue，其余按 stride 跳过
- **自动 decimation** · `maxPoints=500000` 大场景抽样后再显示，浏览器不卡
- **抛 `PLYParseError`** 而不是返回 undefined · 调用方 UI 层可捕获显示

**API**：
```ts
parsePLY(buffer, { maxPoints? }) → {
  vertexCount, positions: Float32Array, colors: Uint8Array | null,
  hasColor, format
}
```

### 2. `frontend-v0.1/components/PointCloudViewer.tsx` · React 组件（+180 行）

**核心特性**：
- 动态 `import()` PLY parser · 未打开产物区的页面零字节
- `THREE.BufferGeometry` + `THREE.Points` 点云渲染
- **手写 orbit control** · 鼠标拖动 yaw/pitch + 滚轮 zoom · 无需 `OrbitControls` 额外 import
- **自动 bbox 居中** · 场景居中、相机自适应距离
- **点尺寸缩放** · 依据 bbox 半径自动算，远近场景视觉一致
- **RGB 支持** · 有色则用 vertexColors，无色则单色蓝
- **清理路径** · `useEffect` return 完整清理 mousedown/mouseup/wheel/resize 监听 + `geom.dispose()` / `mat.dispose()` / `renderer.dispose()`

**UI overlay**：
- 加载中蒙层
- 错误蒙层（PLY 损坏 / 缺 xyz）
- 底部状态栏 · "N 点 · 带 RGB · 鼠标拖动旋转 · 滚轮缩放"

### 3. `frontend-v0.1/app/dashboard/scenes/[id]/page.tsx` · 集成到详情页（+50 行）

**列表新增「预览」按钮**：
- 仅 `.ply` 文件显示
- 硬顶 200MB · 超限提示 "下载到桌面 viewer 查看"
- 点击后 fetch + arrayBuffer + 塞进 PointCloudViewer
- 可关闭 · 释放 buffer 引用 · 释放 GPU 资源

### 4. `frontend-v0.1/tests/ply-parser.test.ts` + `run-ply-tests.sh` · 14 独立测试

**为什么不用 vitest/jest**：项目还没有测试基建，为一个 pure module 引入完整 test infra 得不偿失。手写 assert-based test + 独立 bash runner，14 tests 跑 0.5s。

**测试覆盖**：

| 测试组 | 覆盖 |
|--------|------|
| **Header 解析 5 tests** | 缺 magic / 缺 end_header / 未知 format / ascii 头 / binary 混合属性 |
| **ASCII 4 tests** | xyz cloud / rgb cloud / 缺 xyz 抛错 / vertexCount=0 |
| **Binary 3 tests** | binary_little_endian xyz / binary rgb / **截断二进制检测**（防止越界读取导致 UB） |
| **Decimation 1 test** | maxPoints=10 → 100 顶点采样为 10 |
| **3DGS 兼容 1 test** | 17 属性/顶点场景下仍正确读 xyz（scale/rot/opacity 全跳过） |

**执行**：
```bash
$ bash frontend-v0.1/tests/run-ply-tests.sh
14/14 tests passed
```

---

## ✅ 完整验证

- 前端 PLY tests · **14/14** 全绿
- 后端累计 · **80/80** 全绿（本轮无后端改动）
- TypeScript tsc --noEmit exit=0（前端全项目）
- three.js 0.160.0 安装成功

---

## 📂 改动文件清单

```
frontend-v0.1/
├── lib/ply-parser.ts                    (+280 行 · 新增)
├── components/PointCloudViewer.tsx       (+180 行 · 新增)
├── tests/ply-parser.test.ts              (+240 行 · 新增, 14 tests)
├── tests/run-ply-tests.sh                (+30 行 · 新增)
├── app/dashboard/scenes/[id]/page.tsx    (+50 行 · 预览按钮+doPreview 函数)
└── package.json                          (+2 deps · three@0.160 + @types/three)
```

**代码规模** · +780 行（前端）

---

## 🔑 端到端流程（已闭合完整）

```
1. uploadFile()                    ← T1.1
2. CAS assemble                    ← T1.1
3. POST /scenes/{sid}/ingest       ← T1.0
4. POST /scenes/{sid}/colmap       ← T1.2 GsplatExecutor.run_colmap
5. POST /scenes/{sid}/train        ← T1.2 GsplatExecutor.run_training
6. POST /scenes/{sid}/artifacts/register (.ply)  ← T1.3
7. GET /scenes/{sid}/artifacts     ← T1.3
8. GET /scenes/{sid}/assets/{aid}/download (fetch → ArrayBuffer)  ← T1.3
9. parsePLY(buffer) + PointCloudViewer render  ← T1.4 · **新增**
10. 客户看得爽 → 决定下载 → 桌面 viewer 漫游  ← T1.3 补齐
```

**T1.0-T1.4 五环全部闭合** — 从"上传源图"到"在线漫游 3D 场景"完整交付链。

---

## 📝 v2.1 T1 路线更新

| 环节 | 状态 |
|------|------|
| T1.0 骨架 | ✅ 完成 |
| T1.1 上传 | ✅ 完成 |
| T1.2 真执行器 | ✅ 完成 |
| T1.3 产物导出 | ✅ 完成 |
| **T1.4 内嵌 viewer** | ✅ 完成（本轮） |
| T1.5 完整 3DGS 光栅化 + Docker CI | ⏳ · 6-8h |
| T1.6 场景商店（跨 org 共享） | ⏳ v2.1 后段 |

**T1.5 优先级**：把点云预览升级到真 3DGS 光栅化，用户能看到高质量漫游而非稀疏点云。

---

**T1.4 状态** · ✅ 完成
**六连击** · v2.0 R23 → T1.0 → T1.1 → T1.2 → T1.3 → T1.4 · 后端 80 tests + 前端 14 tests 全绿
