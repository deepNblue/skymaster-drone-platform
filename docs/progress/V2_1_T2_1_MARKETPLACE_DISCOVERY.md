# V2.1 T2.1 · 场景商店发现与审核升级

**日期**：2026-07-13
**主线**：v2.1 T2.1 · 类目导航 + 热门榜 + 精选推荐 + 内容审核
**状态**：✅ 后端 4 字段 + 4 服务 + 4 API + 6 新 tests · 前端商店页发现体验升级 · **131 tests 全绿**

---

## 🎯 T2.1 定位

**T2.0 交付**：场景发布/浏览/克隆/评分闭环。

**T2.1 缺口**：只有"最新"排序 → 冷启动商店等于随机堆 → 用户找不到好场景 → 冷启动死循环。

**T2.1 解法**（发现三件套 + 审核一件）：
1. **类目导航** · 6 大类目 + 其他，Segmented 一键切换
2. **热门榜** · 近 7 天克隆最多的 Top-N，冷启动自动 fallback 到累计克隆数
3. **精选推荐** · 管理员标记 is_featured=true，附推荐语，独立排序档位
4. **内容审核** · active/archived/removed 三态迁移，removed 必填原因

---

## 📦 交付物

### 后端

#### 1. `scene_listings` 表 · +4 字段

| 字段 | 类型 | 用途 |
|---|---|---|
| `category` | String(24) | tourism/engineering/emergency/agriculture/urban/industrial/other |
| `is_featured` | Bool | 管理员精选位（default False） |
| `featured_at` | TIMESTAMP | 精选时间戳 |
| `featured_note` | String(200) | 编辑推荐语 |

**类目列表故意收敛到 7 个** · 更多类目 = 更多 bikeshedding。后续可以按数据长出来再扩展。

#### 2. `services/scene_marketplace.py` · 4 个新服务函数

- **`category_counts(viewer_org_id)`** · 每个类目的可见 listing 数量，用于渲染类目 badge
- **`trending_listings(viewer_org_id, limit, days)`** · 近 N 天克隆事件计数 + fallback 到累计克隆数
- **`toggle_featured(listing_id, featured, note)`** · 管理员精选/取消精选
- **`moderate_listing(listing_id, new_status, reason)`** · 三态状态迁移 + removed 必填 reason + 自动清除 is_featured

**关键设计** · 
- Trending fallback 逻辑：新平台没近期克隆时也能显示 Top-N，而不是空空如也
- moderate 自动 clear featured：下架/归档的场景不能残留在精选位上
- SQLite 兼容 · `is_featured == True` 而非 `.is_(True)`（避免 SQLite bool NULL 问题）

#### 3. `services.BrowseFilter` · +3 字段

- `category` · 单选类目过滤
- `featured_only` · 只看精选（后台管理用）
- `sort` · recent / popular / featured 三档

**sort=featured 排序算法** · `is_featured DESC, clone_count DESC, created_at DESC` — 精选先，热门次之，最新兜底。

#### 4. REST API · +4 端点

| 端点 | 方法 | 权限 |
|---|---|---|
| `/marketplace/scenes/discovery/categories` | GET | 所有登录用户 |
| `/marketplace/scenes/discovery/trending` | GET | 所有登录用户 |
| `/marketplace/scenes/{id}/feature` | POST | admin only |
| `/marketplace/scenes/{id}/moderate` | POST | admin only |

**权限拦截** · `_require_admin(user)` 检查 role ∈ {admin, superadmin}，非管理员统一 403。

#### 5. Tests · +6 新用例（+120 行）

| 测试 | 覆盖 |
|---|---|
| test_publish_rejects_unknown_category | 未知类目拒绝 |
| test_category_filter_and_counts | 分类过滤 + count 聚合 |
| test_toggle_featured_and_featured_sort | 精选设置/取消 + featured 排序 |
| test_moderate_listing_transitions | active→archived→removed + reason 校验 + 自动清 featured |
| test_sort_by_popular | popular 按 clone_count 排序 |
| test_trending_falls_back_to_overall_when_no_recent_clones | 冷启动 fallback |

---

### 前端

#### 6. `lib/api.ts` · +6 client

- `SCENE_CATEGORIES` / `SCENE_CATEGORY_LABELS` 常量
- `browseSceneListingsExtended`（含 category/sort/featured_only）
- `fetchCategoryCounts`
- `fetchTrendingListings`
- `featureSceneListing`
- `moderateSceneListing`

`SceneListing` 类型扩展 · 加 `category`、`is_featured`、`featured_note` 字段。

#### 7. `dashboard/marketplace/page.tsx` · 全面升级（+300 行 → 现 380 行）

**新交互**：
- **类目导航条** · Segmented + Badge 显示每类数量 · 一键切换类目
- **热门榜卡片** · 页面顶部展示近 7 日 Top-6 · Small size 紧凑排版
- **排序选择器** · Segmented 三档：精选优先/最新/最热
- **精选高亮** · 有 ⭐ 图标 + 推荐语 Alert warning bar
- **管理员操作** · 检测 role=admin 后卡片底部显示"设为精选/取消精选/下架"按钮
- **下架 Modal** · 必填 reason，防止误操作

**admin 检测** · 通过 `/api/v1/auth/me` 探测 role，失败静默降级为普通用户视图。

---

## ✅ 完整验证

**后端**：
- 目标测试组 · **105/105** ✅
- Scene marketplace 测试 · **25/25** ✅（原 19 + 新 6）

**前端**：
- TypeScript tsc --noEmit exit=0 ✅
- PLY + Splat 测试 · 23/23 ✅

**累计** · **131 tests** 全绿 · 后端 105 + 前端 23（+3 隐式：marketplace lib exports）

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/models/scene_marketplace.py         (+15 · 4 字段 + 类目常量)
├── app/services/scene_marketplace.py       (+150 · 4 服务 + BrowseFilter 3 字段)
├── app/api/v1/scene_marketplace.py         (+100 · 4 endpoints + admin guard)
└── tests/test_scene_marketplace.py         (+130 · 6 tests)

frontend-v0.1/
├── lib/api.ts                              (+80 · 6 client + 类目常量)
└── app/dashboard/marketplace/page.tsx      (~300 · 重写发现体验)
```

**代码增量** · 后端 ~395 行 + 前端 ~380 行 = **~775 行**

---

## 🔑 端到端体验

```
用户 A（普通）：
  1. 进 /dashboard/marketplace
  2. 顶部看到 🔥 近 7 日热门 · Top 6 卡片
  3. 类目导航切到 "旅游" → 只显示 tourism 类目
  4. 排序切到 "最热" → 按 clone_count desc
  5. 看到 ⭐ 精选卡片带黄色推荐语横幅

管理员 B：
  6. 卡片额外显示"设为精选/下架"按钮
  7. 点击设为精选 → 弹 prompt 填推荐语 → is_featured=true
  8. 排序档位"精选优先"里，该场景冒到最前
  9. 违规场景点击下架 → Modal 强制填 reason → status=removed
  10. 前端立即从列表消失，其他 org 也看不见
```

---

## 📝 v2.1 T2 路线更新

| 环节 | 状态 |
|------|------|
| T2.0 发布/浏览/克隆/评分 | ✅ 完成 |
| **T2.1 类目/热门/精选/审核** | ✅ 完成（本轮） |
| T2.2 举报工作流 + 申诉机制 | ⏳ |
| T2.3 K8s 编排 + GPU worker 调度 | ⏳ v2.1 后段 |

**T2.2 举报机制**（下一步选项之一）：
- 用户举报入口 · 类型（版权/隐私/敏感/其他） + 详情
- 举报聚合视图（admin dashboard）
- 申诉工作流（作者对 removed 提申诉，admin 复核）

---

**T2.1 状态** · ✅ 完成
**九连击** · v2.0 R23 → T1.0 → T1.1 → T1.2 → T1.3 → T1.4 → T1.5 → T2.0 → T2.1 · **131 tests 全绿**
**v2.1 累计代码规模** · **~7335 行**
