# V2.1 T2.0 · 场景商店（Scene Marketplace）

**日期**：2026-07-13
**主线**：v2.1 T2.0 · 跨 org 场景发布/浏览/克隆/评分
**状态**：✅ 后端 4 表 + 服务层 + REST API + 19 tests · 前端商店页 + 详情页发布按钮 · 累计 122 tests 全绿

---

## 🎯 T2.0 定位

**T1 交付**：单个 org 内部完整 3DGS 管道（上传→COLMAP→训练→预览→下载）。

**T2.0 交付**：**打破 org 孤岛** — 允许 org 把自己训练好的场景「发布」到公开商店，其他 org 「一键克隆」到自己工作区，并附评分/热度/许可元数据。

**差异化立论**：
- 大疆司空 2：完全无跨 org 场景分享
- 阿里云海外：仅限自建租户下资产复用
- **SkyMaster 目标：3DGS 场景的"HuggingFace Datasets"** — 央企、测绘公司、政府应急部门可以互相共享标杆场景（如"成都东站高铁枢纽"、"九寨沟核心景区"）

---

## 🚫 明确不做（本轮边界）

- ❌ 付费下载 · price_cents 字段已预留，实际计费走 v2.3
- ❌ 精选/编辑推荐 · v2.1 T2.1 单独做
- ❌ 联邦搜索/跨集群同步 · v2.2 空间智能路线
- ❌ 内容审核工作流 · 先上 status=removed 字段占位，审核工具走 v2.1 T2.2

**本轮聚焦**：**公开列表 + 克隆 + 评分**三个最小闭环。

---

## 📦 交付物

### 后端

#### 1. `app/models/scene_marketplace.py` · 3 张 ORM 表（+180 行）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `scene_listings` | 主表，商品目录 | slug（唯一）· title/description/tags · visibility(public/org_only/unlisted) · license(CC0/CC-BY/...) · price_cents · n_gaussians（发布时快照，不动） |
| `scene_listing_reviews` | 0-5 星评分 + 评论 | UniqueConstraint(listing_id, user_id) · 每用户每场景仅 1 条，重复调用是 upsert |
| `scene_listing_clones` | 克隆溯源记录 | 谁在什么时候克隆到哪个 scene_id · 用于做热度榜和反爬 |

**核心设计原则** · **immutable snapshot** · 场景重训后 listing 不自动更新，必须重新 publish。给买家稳定的溯源链。

#### 2. `app/services/scene_marketplace.py` · 纯业务逻辑（+320 行）

- **`slugify()`** · title → URL slug · 处理 CJK 全 fallback 到 `scene-{uuid12}` · 单元测试 6 例
- **`publish_scene()`** · 场景状态白名单 (ready/archived) + license 白名单 + slug 唯一约束 + 快照 metrics
- **`browse_listings()`** · **visibility-aware 查询** · 匿名/跨 org 只看 public · 同 org 额外看 org_only · unlisted 靠直链
- **`clone_listing()`** · 检查可见性 → 复制 metadata → 在克隆方 org 新建 `Scene(status=archived)` + 写溯源 record + `clone_count += 1`
- **`upsert_review()`** · 双写查询兼容 SQLite（避免 PG-only UPSERT），保证同一用户改评分不产生重复行
- **`listing_rating_summary()`** · count + avg rating 一次查询

**为什么克隆时新 Scene status=archived**：克隆本质是"引用"而非"深拷贝原始图像"。默认只读，用户想在克隆基础上重训需手动 reset。

#### 3. `app/api/v1/scene_marketplace.py` · REST API（+180 行）

| 端点 | 方法 | 用途 |
|---|---|---|
| `/marketplace/scenes` | POST | 发布 |
| `/marketplace/scenes` | GET | 分页浏览 · q/tags/license/min_gaussians/org_id 过滤 |
| `/marketplace/scenes/{id}/clone` | POST | 一键克隆 |
| `/marketplace/scenes/{id}/reviews` | POST | 评分（upsert） |
| `/marketplace/scenes/{id}/rating` | GET | 平均分/评论数 |

**错误码语义化** · SceneNotPublishable→404 · SlugConflict→409 · ListingNotVisible→403 · 其他 400。

#### 4. `tests/test_scene_marketplace.py` · **19 tests**（+250 行）

| 测试类别 | 数量 | 覆盖 |
|---|---|---|
| slugify pure 单测 | 6 | 空格/多分隔符/CJK/超长截断/数字保留/前后 dash strip |
| publish DB 用例 | 5 | happy path / draft 拒绝 / 跨 org 拒绝 / 未知 license / slug 冲突 / CJK title 自动 slug |
| browse | 3 | visibility 跨 org / 同 org / n_gaussians 过滤 |
| clone | 2 | 新建 Scene + 溯源 + clone_count / org_only 跨 org 拒绝 |
| review | 2 | upsert 更新 + summary 求均值 / 1-5 越界拒绝 |
| pagination | 1 | limit/offset 边界 |

---

### 前端

#### 5. `frontend-v0.1/lib/api.ts` · +5 个 API client（+80 行）

- `publishSceneListing`
- `browseSceneListings`（支持 q/tags/license/min_gaussians/org_id/limit/offset）
- `cloneSceneListing`
- `reviewSceneListing`
- `sceneListingRating`

#### 6. `frontend-v0.1/app/dashboard/marketplace/page.tsx` · 商店主页（+220 行）

- **筛选栏** · 搜索框 + license 选择 + 最小高斯数
- **卡片网格** · 3 列响应式 · 标题 + license Tag + 描述 + tags + n_gaussians/n_points/clone_count 数据 + 克隆按钮
- **分页** · 每页 12 条 · 上一页/下一页 + `N-M / total` 显示
- **空状态** · 引导用户到场景详情页发布

#### 7. `frontend-v0.1/app/dashboard/scenes/[id]/page.tsx` · 场景详情新增发布按钮

- `status ∈ {ready, archived}` 时显示 "发布到场景商店" 按钮
- 弹 prompt 输入 title，默认走 `CC-BY-NC` license + `public` visibility
- 发布成功后 message.success 显示 slug

#### 8. `frontend-v0.1/app/dashboard/layout.tsx` · 左侧菜单增加 🛒 场景商店入口

---

## ✅ 完整验证

**后端**：
- 目标测试组 · **99/99** ✅（原 80 + 新 19）
- Marketplace 新测 · 19/19 ✅（含 slugify pure 单测 6 + DB 集成 13）

**前端**：
- TypeScript tsc --noEmit exit=0 ✅
- PLY + Splat 测试 · 23/23 ✅

**累计** · **122 tests** 全绿

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/models/scene_marketplace.py       (+180 · 新增 3 表)
├── app/models/__init__.py                (+5 · exports)
├── app/models/model_marketplace.py        (2 · organization FK 名字修复)
├── app/services/scene_marketplace.py     (+320 · 新增)
├── app/api/v1/scene_marketplace.py       (+180 · 新增)
├── app/api/v1/router.py                  (+2 · 路由挂载)
├── app/api/v1/scenes_upload.py           (~4 · 修 204 Response 兼容)
├── tests/conftest.py                     (+1 · scene_marketplace 到 imports)
└── tests/test_scene_marketplace.py       (+250 · 19 tests)

frontend-v0.1/
├── lib/api.ts                            (+80 · marketplace client)
├── app/dashboard/marketplace/page.tsx    (+220 · 商店主页)
├── app/dashboard/scenes/[id]/page.tsx    (+30 · 发布按钮)
└── app/dashboard/layout.tsx              (+3 · 菜单入口)
```

**代码增量** · 后端 ~950 行 + 前端 ~330 行 = **~1280 行**

---

## 🔑 端到端流程

```
Org A：
  1. 训练完 3DGS 场景 → 状态 ready
  2. 点击"发布到场景商店" → 输入 title
  3. Backend: publish_scene → 创建 SceneListing(status=active, public)

Org B（跨 org 用户）：
  4. 打开 /dashboard/marketplace
  5. 搜索 "成都" 或过滤 min_gaussians≥1M
  6. 点击卡片 "克隆到我的工作区"
  7. Backend: clone_listing → 在 Org B 新建 Scene(archived, [clone] 前缀)
  8. Frontend 提示 "已克隆至 xxx"
  9. Org B 到自己的场景列表看到克隆场景，可继续操作/评分
```

**跨 org 场景生态第一步已跑通**。

---

## 📝 v2.1 T2 路线更新

| 环节 | 状态 |
|------|------|
| **T2.0 发布/浏览/克隆/评分** | ✅ 完成（本轮） |
| T2.1 精选/编辑推荐 | ⏳ |
| T2.2 内容审核 workflow | ⏳ |
| T2.3 K8s 部署编排（GPU worker 调度） | ⏳ v2.1 后段 |

**下一步 T2.1**：热门榜 + 编辑推荐 + 类目导航（旅游/工程/应急/农业）。

---

**T2.0 状态** · ✅ 完成
**八连击** · v2.0 R23 → T1.0 → T1.1 → T1.2 → T1.3 → T1.4 → T1.5 → T2.0 · **122 tests 全绿**
**v2.1 代码规模总计** · 后端 ~3300 行 + 前端 ~3030 行 + Docker/CI ~230 行 = **~6560 行**
