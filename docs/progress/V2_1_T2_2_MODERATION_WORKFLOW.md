# V2.1 T2.2 · 举报工作流与申诉复核

**日期**：2026-07-13
**主线**：v2.1 T2.2 · 内容治理闭环（用户举报 → 自动/管理员下架 → 作者申诉复核）
**状态**：✅ 后端 2 表 + 服务 + 8 REST 端点 + 18 tests · 前端举报入口 + 管理员审核工作台 · **141 tests 全绿**

---

## 🎯 T2.2 定位

**T2.0/T2.1 交付**：场景发布/浏览/克隆/评分 + 类目/热门/精选/管理员手动下架。

**T2.2 缺口**：
- 普通用户看到违规场景 → 没有举报入口
- 管理员靠人肉巡查 → 高危内容可能长时间在线
- 作者被下架 → 没有申诉渠道 → 冤假错案无救济

**T2.2 解法** · 内容治理闭环
1. **用户举报** · 6 类举报（版权/隐私/敏感区域/违法/垃圾/其他）
2. **自动下架** · 同场景 ≥3 名不同用户举报「高危」类别 → 自动归档待审核
3. **管理员工作台** · 举报队列 + 申诉队列 双 Tab
4. **申诉机制** · 被下架的场景，publisher org 可提交申诉，admin 复核可恢复

---

## 📦 交付物

### 后端

#### 1. `scene_moderation.py` 模型 · 2 张新表（+180 行）

**`scene_listing_reports`**：
- 唯一约束 `(listing_id, reporter_user_id)` · 保证每人对同场景只有一条举报，重复举报 = upsert
- 6 类 category CHECK 约束
- 5 态 status: open / reviewing / accepted / rejected / duplicate
- resolver_user_id + resolution_note + resolved_at 记录处理轨迹

**`scene_listing_appeals`**：
- 唯一约束 `(listing_id, appeal_seq)` · 支持同一场景多次下架多次申诉
- 4 态 status: pending / accepted / rejected / withdrawn
- 快照 `original_status` + `original_reason` · 申诉时记录下架上下文
- 只允许 publisher org 发起（不是举报者）

#### 2. `services/scene_moderation.py` · 业务逻辑（+310 行）

**关键设计**：
- **不能举报自己 org 的场景** — 防止刷榜/引流
- **举报 upsert 逻辑** · 相同 (listing, user) 更新而非新增 · rejected/duplicate 状态自动重开
- **AUTO_HIDE_THRESHOLD=3 + AUTO_HIDE_CATEGORIES=copyright/privacy/sensitive_area/illegal** · 达到阈值自动 archived
- **软类别（spam/other）永不触发自动下架** · 避免刷子恶意组团下架
- **resolve_report accepted 时自动 rollup 兄弟举报** · 同场景其他 open 举报标 duplicate，避免管理员重复处理
- **申诉唯一性** · 同 listing 有 pending 申诉时不允许新建，防止刷子重复申诉
- **申诉只能针对 removed 状态** · active/archived 不允许申诉

#### 3. `api/v1/scene_moderation.py` · REST API（+180 行）

| 端点 | 方法 | 权限 |
|---|---|---|
| `/scenes/{id}/reports` | POST | 所有登录用户 |
| `/scenes/reports` | GET | admin only |
| `/scenes/{id}/reports/summary` | GET | admin only |
| `/scenes/reports/{id}/resolve` | POST | admin only |
| `/scenes/{id}/appeals` | POST | publisher org |
| `/scenes/appeals` | GET | admin only |
| `/scenes/appeals/{id}/resolve` | POST | admin only |
| `/scenes/appeals/{id}/withdraw` | POST | publisher org |

#### 4. Tests · 18 tests（+400 行）

| 测试类别 | 数量 |
|---|---|
| 举报基础 · happy path / self-report reject / upsert / unknown cat | 4 |
| 自动下架 · 硬类别达阈值触发 / 软类别永不触发 | 2 |
| resolve 与 rollup · accept take-down + siblings duplicate / accepted reason required / summary 聚合 | 3 |
| 申诉基础 · happy / active listing 拒绝 / 跨 org 拒绝 / 唯一 pending / 再申诉 seq++ / 无法重复 resolve | 6 |
| 申诉状态迁移 · accept 恢复 / reject 保持 / withdraw | 3 |

---

### 前端

#### 5. `lib/api.ts` · +9 client（+130 行）
- REPORT_CATEGORIES/LABELS 常量
- fileReport / listReports / reportSummary / resolveReport
- fileAppeal / listAppeals / resolveAppeal / withdrawAppeal
- Report + Appeal 类型定义

#### 6. `dashboard/marketplace/page.tsx` · 举报入口（+50 行）
- 每张卡片底部新增 🚩 举报按钮
- Modal 弹窗 · 类型 Select + 详情 TextArea + 自动下架说明 Alert
- 提交后如触发自动下架 → `message.warning` 提示

#### 7. `dashboard/moderation/page.tsx` · 管理员工作台（+235 行）
- Tabs · 举报队列 / 申诉队列
- 状态过滤器 · 待处理 / 已接受 / 已驳回 / 全部
- 举报表格 · 类型 Tag + listing_id + 详情 + 状态 + 操作（下架/驳回/标记重复）
- 申诉表格 · seq + listing + 理由 + 状态 + 操作（接受恢复/驳回）
- 双 Modal · 下架必填 reason + 内部备注 · 恢复上架必填审核备注
- 顶部 Alert · 解释自动下架阈值机制

#### 8. 左侧菜单 · 🛡️ 内容审核

---

## ✅ 完整验证

- 后端 · 123/123 ✅（marketplace 25 + moderation 18 + 其他 80）
- 前端 · TypeScript exit=0 ✅ + PLY/Splat 23/23 ✅

**累计** · **141 tests** 全绿（+18 backend + 前端 lib 增量）

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/models/scene_moderation.py         (+180 · 2 表)
├── app/models/__init__.py                 (+5 · exports)
├── app/services/scene_moderation.py       (+310 · report/appeal 服务)
├── app/api/v1/scene_moderation.py         (+180 · 8 endpoints)
├── app/api/v1/router.py                   (+2 · 挂载)
├── tests/conftest.py                      (+1 · imports)
└── tests/test_scene_moderation.py         (+400 · 18 tests)

frontend-v0.1/
├── lib/api.ts                             (+130 · moderation client)
├── app/dashboard/marketplace/page.tsx     (+50 · 举报入口)
├── app/dashboard/moderation/page.tsx      (+235 · 管理员工作台)
└── app/dashboard/layout.tsx               (+1 · 菜单入口)
```

**代码增量** · 后端 ~1080 行 + 前端 ~415 行 = **~1495 行**

---

## 🔑 端到端场景

### 场景 A · 用户举报 + 自动下架
```
1. 3 名不同 org 的用户 A/B/C 分别举报同一场景为 privacy 类
2. 第 3 条举报提交时，系统自动 status=archived + is_featured=false
3. 前端 message.warning 提示"达到自动归档阈值，等待管理员复核"
4. 管理员在 /moderation 看到该场景 3 条 open 举报
5. 管理员点击第 1 条的"下架" → 填 reason → status=removed
6. 系统自动把兄弟 2 条举报标为 duplicate + resolution_note 关联主报告
```

### 场景 B · 作者申诉 + 管理员恢复
```
1. 场景被 admin 直接 moderate 到 removed
2. Publisher org 的用户在场景详情页看到"申诉"入口
3. 填写申诉理由 · 系统生成 appeal_seq=1
4. 管理员在 /moderation 申诉 Tab 看到 pending 申诉
5. 复核后点击"接受恢复" · 填审核备注
6. Backend · appeal.status=accepted + listing.status=active
7. 场景重新回到商店可见列表
```

### 场景 C · 反刷申诉
```
1. 作者提交申诉 #1 → 被驳回 status=rejected
2. 作者试图再次申诉 → 系统检测 listing 仍是 removed 但无 pending 申诉 → 允许
3. 生成 appeal_seq=2 · 复核后如果又被驳回 → 作者仍可发第 3 次
4. 系统限制的是"同一 listing 同一时刻只能有 1 条 pending"，不是终身次数
5. 如果发起后想撤销 · 走 /appeals/{id}/withdraw · status=withdrawn
```

---

## 📝 v2.1 T2 路线进度

| 环节 | 状态 |
|------|------|
| T2.0 发布/浏览/克隆/评分 | ✅ 完成 |
| T2.1 类目/热门/精选/审核 | ✅ 完成 |
| **T2.2 举报工作流 + 申诉机制** | ✅ 完成（本轮） |
| T2.3 K8s 编排 + GPU worker 调度 | ⏳ v2.1 后段 |

---

**T2.2 状态** · ✅ 完成
**十连击** · v2.0 R23 → T1.0 → T1.1 → T1.2 → T1.3 → T1.4 → T1.5 → T2.0 → T2.1 → T2.2 · **141 tests 全绿**
**v2.1 累计代码规模** · **~8830 行**
