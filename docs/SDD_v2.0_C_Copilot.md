# SkyMaster v2.0 · Track C Copilot Agent SDD

- **版本**：v0.1-draft · 2026-07-09
- **对齐**：PRODUCT_SPEC §3.15 / v2.0 Roadmap Track C
- **目标**：3 个月内交付 Agent Copilot v1 —— 自然语言指令 → 任务规划 → 审批门禁 → 可追溯执行

---

## 1. Copilot 定位

**Copilot 不是聊天机器人，是无人机指挥中心的"参谋长"**：
- 理解自然语言指令（例："沿电力线巡检长安街 3km"）
- 生成候选任务方案（多个航线可选）
- 主动做**风险检查**（禁飞区/续航/天气/报备）
- **强制人工审批门禁**（涉及飞行/删除/报备三类动作必须人工点确认）
- 全程 Trace 可追溯（含 prompt / tool call / 输出 / 审批人 / 时间戳）

**明确不做的事**：
- ❌ 不自动下发飞行任务（永远需要人工审批）
- ❌ 不自主学习/记忆客户数据（每 session 独立，敏感信息脱敏）
- ❌ 不做闲聊/情感陪伴（拒绝无关问题）

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────┐
│           Web Console · Copilot Drawer              │
│  紫色抽屉 · 打字机效果 · 强制审批弹窗                 │
└────────────────────────┬────────────────────────────┘
                         │ SSE / WebSocket
                         ▼
┌─────────────────────────────────────────────────────┐
│               Copilot Gateway                       │
│  · Session Manager  · Rate Limit                    │
│  · Prompt Guard     · Output Sanitizer              │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│           Agent Orchestrator (LangGraph)            │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │Intent    │──▶│Planner   │──▶│Executor  │         │
│  │Classifier│   │(LLM+RAG) │   │(工具调用)│         │
│  └──────────┘   └──────────┘   └────┬─────┘         │
│                                     │               │
│                              ┌──────▼──────┐        │
│                              │Approval Gate│        │
│                              │(人工审批门禁)│       │
│                              └──────┬──────┘        │
│                                     │               │
│                                     ▼               │
│                              ┌─────────────┐        │
│                              │Trace Logger │        │
│                              └─────────────┘        │
└─────────────────┬───────────────────────────────────┘
                  │ Function Call
                  ▼
┌─────────────────────────────────────────────────────┐
│                  Tool Registry                      │
│  create_mission · plan_waypoints · check_airspace   │
│  submit_approval · query_weather · get_battery      │
│  list_drones · dispatch_mission · abort_mission     │
└─────────────────────────────────────────────────────┘
```

---

## 3. LLM 选型

| 模型 | 用途 | 部署 | 决策 |
|---|---|---|---|
| **DeepSeek-V3 / Qwen3-72B** | 主对话 + Planner | 云端 API（火山/阿里/自建 vLLM） | ✅ 首选 · 中文强 · Function Call 稳定 |
| **Qwen2.5-7B-Instruct** | 边缘/离线场景 | 客户本地 GPU | ✅ 私有化客户备选 |
| GPT-4o / Claude 3.5 | 对标 | 海外 API | ❌ 政企场景合规不达标 |

**私有化部署优先级**：客户敏感数据不出域时，走客户机房 vLLM + Qwen2.5-7B。

---

## 4. Agent 核心组件

### 4.1 Intent Classifier（意图分类）

**5 类核心意图**（v2.0）：
```python
class Intent(str, Enum):
    PLAN_MISSION       = "plan_mission"        # 规划任务
    QUERY_STATUS       = "query_status"        # 查询状态
    ANALYZE_MEDIA      = "analyze_media"       # 分析历史媒体
    SUBMIT_APPROVAL    = "submit_approval"     # 提交报备
    EMERGENCY_ACTION   = "emergency_action"    # 紧急处置（返航/中止）
    UNSUPPORTED        = "unsupported"         # 拒绝
```

**分类策略**：
- 短句（≤30 字）→ 关键词规则优先
- 长句 → LLM few-shot 分类
- **强制拒绝**：闲聊/黄暴/政治敏感 → UNSUPPORTED

### 4.2 Planner（规划器）

**输入**：Intent + 用户 prompt + 上下文（当前用户 org、可见 drone、当前时间/天气）
**输出**：结构化计划（JSON），包含：
```json
{
  "steps": [
    {"tool": "check_airspace", "args": {"geo": [...]}, "reason": "先验证空域"},
    {"tool": "plan_waypoints", "args": {"path": "..."}, "reason": "生成航线"},
    {"tool": "check_battery", "args": {"drone_id": "..."}, "reason": "预估续航"},
    {"tool": "submit_approval", "args": {"mission_id": "..."}, "reason": "自动报备"}
  ],
  "risks": [
    "任务经过长安街禁飞区，需人工确认",
    "预计飞行 25 分钟，电池余量 78% 边界"
  ],
  "requires_human_approval": true,
  "confidence": 0.86
}
```

**RAG 增强**：
- 用户历史任务模板检索（Top-5）
- 客户 SOP 文档向量库
- 空域政策/法规知识库（长期）

### 4.3 Approval Gate（⭐ 核心安全组件）

**强制触发条件**（任一即需人工审批）：
- 涉及飞行动作（dispatch/abort/RTL）
- 涉及数据变更（删除/修改任务）
- 涉及报备提交
- `confidence < 0.8`
- 检测到 `risks` 非空
- 涉及管制/禁飞空域

**审批 UI**：
```
┌───────────────────────────────────┐
│ ⚠ 需人工审批                       │
├───────────────────────────────────┤
│ 动作：向 DR-003 下发巡检任务       │
│ 航线：长安街电力线走廊 3.2km       │
│ 风险：                            │
│  · 经过管制区 (需 UOM 报备)        │
│  · 预计耗时 25 分钟                │
│  · 电池余量 78% 边界              │
│                                   │
│ [❌ 取消]   [👁 查看详情]  [✅ 批准]│
└───────────────────────────────────┘
```

**审批策略**：
- 敏感动作**双人审批**（Op + Supervisor）
- 24 小时未审批自动过期
- 审批人可修改 args 后再下发

### 4.4 Executor（工具执行器）

**执行原则**：
- 一次仅执行一个 tool（不做 parallel tool call）
- 每次调用前后写 Trace
- 工具失败重试 ≤ 2 次
- 敏感工具（dispatch/delete）需通过 Approval Gate

### 4.5 Trace Logger（可追溯）

**每次 session 完整记录**：
```json
{
  "trace_id": "uuid",
  "user": "duoduo",
  "org_id": "xxx",
  "started_at": "...",
  "ended_at": "...",
  "prompt_input": "沿电力线巡检长安街 3km",
  "intent": "plan_mission",
  "steps": [
    {"idx": 0, "tool": "check_airspace", "args": {...}, "result": {...}, "duration_ms": 340},
    {"idx": 1, "tool": "plan_waypoints", ...},
    ...
  ],
  "approval": {
    "required": true,
    "approver_id": "user:supervisor-01",
    "approved_at": "...",
    "modifications": {...}
  },
  "output_final": {...},
  "llm_calls": [
    {"model": "deepseek-v3", "prompt_tokens": 1234, "completion_tokens": 456}
  ],
  "cost_cent": 12
}
```

---

## 5. 数据模型

```sql
-- Copilot 会话
CREATE TABLE copilot_sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    user_id      UUID NOT NULL,
    started_at   TIMESTAMPTZ DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    total_cost_cent INT DEFAULT 0,
    total_tokens INT DEFAULT 0
);

-- Trace 主表
CREATE TABLE copilot_traces (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID NOT NULL REFERENCES copilot_sessions(id),
    prompt       TEXT NOT NULL,
    intent       VARCHAR(40),
    confidence   REAL,
    output       JSONB,
    started_at   TIMESTAMPTZ DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    status       VARCHAR(20),   -- 'planning'|'approving'|'executing'|'done'|'canceled'|'error'
    error        TEXT
);

-- Trace 步骤（每次 tool 调用）
CREATE TABLE copilot_trace_steps (
    id         BIGSERIAL PRIMARY KEY,
    trace_id   UUID NOT NULL REFERENCES copilot_traces(id),
    idx        INT NOT NULL,
    tool       VARCHAR(60) NOT NULL,
    args       JSONB,
    result     JSONB,
    duration_ms INT,
    error      TEXT,
    ts         TIMESTAMPTZ DEFAULT now()
);

-- 审批记录
CREATE TABLE copilot_approvals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id     UUID NOT NULL REFERENCES copilot_traces(id),
    required_reason TEXT,
    approver_id  UUID,
    approved_at  TIMESTAMPTZ,
    decision     VARCHAR(20),  -- 'approved'|'rejected'|'expired'|'modified'
    modifications JSONB,
    comment      TEXT
);

-- LLM 调用明细
CREATE TABLE copilot_llm_calls (
    id           BIGSERIAL PRIMARY KEY,
    trace_id     UUID NOT NULL,
    model        VARCHAR(60),
    prompt_tokens INT,
    completion_tokens INT,
    duration_ms  INT,
    cost_cent    INT,
    ts           TIMESTAMPTZ DEFAULT now()
);
```

---

## 6. 接口设计

### 6.1 REST · `/api/v2/copilot`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/sessions` | 开启会话 |
| POST | `/sessions/{id}/messages` | 提交用户消息（SSE 返回） |
| GET  | `/sessions/{id}/traces` | 查看该会话 trace 列表 |
| GET  | `/traces/{id}` | Trace 详情（含 steps） |
| POST | `/traces/{id}/approve` | 审批 · body: `{decision, modifications, comment}` |
| POST | `/traces/{id}/cancel` | 取消 |
| GET  | `/traces/{id}/export` | 导出完整 trace PDF |

### 6.2 SSE 流式返回

```
POST /sessions/{id}/messages
Content-Type: text/event-stream

event: intent
data: {"intent": "plan_mission", "confidence": 0.92}

event: step
data: {"idx": 0, "tool": "check_airspace", "status": "start"}

event: step
data: {"idx": 0, "tool": "check_airspace", "status": "done", "result": {...}}

event: token
data: {"delta": "已识别 4 个"}

event: token
data: {"delta": "关键航点..."}

event: approval_required
data: {"trace_id": "...", "reason": "涉及管制区飞行", "detail": {...}}

event: done
data: {"trace_id": "...", "status": "waiting_approval"}
```

---

## 7. Tool Registry（可调用工具）

**v2.0 内置 12 个工具**：

| Tool | 权限级别 | 说明 |
|---|---|---|
| `list_drones` | 只读 | 列出可见无人机 |
| `get_drone_status` | 只读 | 单机状态 |
| `check_airspace` | 只读 | 空域合规查询 |
| `query_weather` | 只读 | 天气查询 |
| `list_missions` | 只读 | 任务列表 |
| `get_mission_detail` | 只读 | 任务详情 |
| `plan_waypoints` | 只读 | 航点生成（不落库） |
| `create_mission` | ⚠ 需审批 | 落库草稿任务 |
| `dispatch_mission` | ⚠ 需审批 | 下发飞行 |
| `abort_mission` | ⚠ 需审批 | 中止 |
| `submit_approval` | ⚠ 需审批 | 触发合规报备 |
| `search_media` | 只读 | 检索历史媒体 |

**Tool 定义 Schema**：
```python
@tool
class PlanWaypointsTool:
    name = "plan_waypoints"
    description = "根据自然语言描述生成航点，不落库"
    args_schema = PlanWaypointsArgs  # pydantic
    permission = "readonly"
    max_calls_per_session = 5

    async def run(self, args: PlanWaypointsArgs, ctx: ToolContext) -> dict:
        ...
```

---

## 8. Prompt 安全（Prompt Guard）

**输入侧防御**（Copilot Gateway 层）：
- 关键词黑名单：政治敏感 / 黄暴 / 越狱指令
- Prompt Injection 检测（"忽略前面所有指令..."）
- 输入长度上限 4000 字符

**输出侧过滤**：
- 敏感字段自动脱敏（身份证/手机号/坐标精度降级）
- 禁止 LLM 输出 raw SQL / raw API URL / raw token
- 无关领域拒答（"我只处理无人机相关问题"）

**Jailbreak 防御**：
- System Prompt 声明后不再暴露
- 用户尝试 prompt-leak → 直接拒绝并记 audit

---

## 9. 12 周 Sprint 拆解

| Week | 任务 | 交付 |
|---|---|---|
| W1 | LangGraph 骨架 + LLM Provider 抽象 | Hello Copilot 能跑 |
| W2 | Tool Registry + 6 只读 tool | 查询类问题可回答 |
| W3 | Intent Classifier · 5 类意图 | 分类准确率 ≥ 90% |
| W4 | Planner + Function Call | 能生成 JSON 计划 |
| W5 | Approval Gate + UI 审批弹窗 | 敏感动作阻断 |
| W6 | 4 敏感 tool（create/dispatch/abort/approval） | 端到端跑通 |
| W7 | Trace Logger + PG 落库 | Trace 完整可查 |
| W8 | SSE 流式 + Copilot Drawer 前端 | UI 打字机效果 |
| W9 | Prompt Guard + 敏感词库 | 5 类越狱测试通过 |
| W10 | RAG · 用户历史模板检索 | 3 个客户 POC |
| W11 | 观测（Langfuse / Opentelemetry） + 计费 | Ops 完备 |
| W12 | v2.0 Track C 发布 + 5 workflow 上线 | 达成验收 |

---

## 10. 内置 5 个 Workflow（v2.0 交付）

| # | Workflow | 触发词示例 | 关键 tool 链 |
|---|---|---|---|
| WF1 | **电力巡检规划** | "沿电力线巡检 xxx" | check_airspace → plan_waypoints → create_mission → submit_approval |
| WF2 | **告警一键复查** | "刚才 3 号机的告警是什么" | list_missions → get_mission_detail → search_media |
| WF3 | **应急返航** | "让所有机立刻返航" | list_drones → abort_mission (逐台，需审批) |
| WF4 | **区域巡查生成** | "巡查邕宁区北部 5 平方公里" | plan_waypoints (grid 模式) → create_mission → submit_approval |
| WF5 | **合规体检** | "本周所有飞行合规吗" | list_missions → check_airspace (回溯) → 生成合规报告 PDF |

---

## 11. 风险与对策

| 风险 | 概率 | 对策 |
|---|---|---|
| LLM 幻觉生成错误航点 | 高 | 强制 Approval Gate + Tool 输出校验 |
| Function Call 失败率 | 中 | 首选 DeepSeek/Qwen · Fine-tune 优化 |
| Prompt Injection 越狱 | 中 | 输入过滤 + Output Sanitizer + system prompt 分层 |
| Token 成本失控 | 中 | 每 session token 上限 + 计费透明 |
| 客户敏感数据泄漏 | 高 | 私有化部署 · 数据不出域 · Trace 脱敏 |
| Trace 存储爆炸 | 低 | 90 天后归档冷存储 |

---

## 12. 与 Track A / Track B 联动

**Copilot ↔ Compliance (Track A)**：
- Copilot 生成任务 → 自动 submit_approval → 状态回订阅 → 审批通过后再 dispatch

**Copilot ↔ Vision AI (Track B)**：
- Copilot 分析告警 → 检索 detections 结果 → 生成人类可读描述
- Copilot 计划任务 → 自动挂载合适的 Vision 模型（电力线任务 → M3 输电线）

---

**文档负责人**：AI 架构组
**版本**：v0.1-draft · 2026-07-09
**下一步**：Track A/B/C 联合 M1 里程碑 kick-off · 具体见 §附录C v2.0 Track 里程碑对照表 🐈
