# SkyMaster v1.2.0 — Copilot v2 × Vision AI Milestone

**发布日期**：2026-07-13  
**分支**：develop → main  
**代号**：Looking-Glass 🔭

---

## 🎯 里程碑意义

SkyMaster **v1.2** 打通了「LLM 智能助理 × 视觉 AI × 3D 战场态势」三条主线，第一次让指挥员可以**用自然语言驱动整套无人机管控闭环**：

> "过去 30 分钟看到什么了？" → LLM 调 Vision AI → 富卡片显示带坐标的检测 → 点击 → 3D 地球飞到目标 → 自动跟随无人机 → 需要时下发派机指令（走审批流）

这是**"看得见的价值"（visible value）**的首个端到端落地，也是 v2.0 六大改进模块中 **Copilot Agent + Vision AI** 的核心内核。

---

## 📦 新增能力

### 🤖 Copilot Agent v2（Function Calling）
- **T4.0** LLM 工具调用循环（10 个工具：查询 6 个 + 敏感 3 个 + 视觉 2 个）
- **T4.1** 敏感操作双向审批端点（approve / reject / modified）
- **T4.2** 前端 SSE 消费 + 审批 UI（`CopilotV2Drawer`）
- **T4.3** 端到端集成测试（3 条主路径全绿）

### 👁️ Vision AI 桥接
- **T5.0** 后端只读查询工具：
  - `list_detections`（drone / mission / label / confidence / 时间窗多维过滤）
  - `detection_stats`（按标签聚合，返回 total + by_label + top_label）
- **T5.1** 前端富卡片渲染（标签调色板、置信度分级配色）

### 🌍 3D 战场态势联动
- **T5.3** 检测行暴露 lat/lng/alt_m，行级点击回调
- **T5.4** CesiumMap 一键 flyTo（1.2s 缓动 + 600m 观察高度 + 自动跟随无人机）

---

## 🛡️ 安全与合规

- 所有 Vision AI 工具**多租户隔离**（`tenant_id == ctx.org_id`）
- 非法 UUID **软失败**（返回 reason，绝不 crash）
- 敏感工具（create_mission / dispatch_mission / abort_mission）**必须走审批循环**
- 审批 API 完备的跨 org 403 防越权

---

## ✅ 测试

| 测试套件 | 通过数 |
|---|---:|
| test_copilot_agent_v2 | 17/17 |
| test_copilot_v2_endpoint | (合并) |
| test_copilot_v2_approval | 8/8 |
| test_copilot_v2_e2e | 3/3 |
| test_vision_tools | 7/7 |
| **合计** | **35/35** |

前端 `npx tsc --noEmit` 无 error。

---

## 🔗 使用入口

- 前端页面：`/dashboard/copilot-v2`
- 后端 API：
  - `POST /api/v1/copilot-v2/sessions` — 建会话
  - `POST /api/v1/copilot-v2/sessions/{sid}/messages` — SSE 流式对话
  - `GET  /api/v1/copilot-v2/approvals/pending` — 待审批
  - `POST /api/v1/copilot-v2/approvals/{aid}/decide` — 决策

---

## 📊 代码规模变动（v1.1 → v1.2）

| 维度 | 数值 |
|---|---:|
| 新增 commit | 11 |
| 新增测试用例 | +28 |
| 新增前端组件 | 4（CopilotV2Drawer / V2ApprovalsInbox / VisionToolResult / 更新 CesiumMap） |
| 新增后端工具 | 2（Vision AI）+ 3（敏感）+ 5（查询） |
| Copilot v2 端到端覆盖率 | 100%（35/35） |

---

## 🚀 下一步（v1.3 / v2.0 展望）

- **T5.5** 组合动作工具：`snapshot_stream` / `focus_camera` / `draw_bbox_on_map`
- **T6.x** Vision AI 实时数据管线（检测入库 + 告警回调 + Redis pub）
- **v2.0 六大模块** 剩余：飞行报备审批 / 3DGS Reality Studio / Community / Model Marketplace
- **实机测试**：v1.1 的 AI 路径规划 + v1.2 的 Copilot 闭环，需在真机上验证

---

**代号 Looking-Glass 的由来**：镜像映射——律师你在飞书上下达一句话，SkyMaster 就在 3D 地球上"看到"、"飞到"、"派到"。透过这面镜子，物理世界和数字孪生第一次真正联动起来。

🐈 —— nanobot
