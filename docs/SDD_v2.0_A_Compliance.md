# SkyMaster v2.0 · Track A 合规审批 SDD

- **版本**：v0.1-draft · 2026-07-09
- **对齐**：PRODUCT_SPEC §3.14 / v2.0 Roadmap Track A / UOM_APPROVAL_RESEARCH v1.0
- **目标**：3 个月内交付 UOM Mock Adapter + 南宁属地 RPA 首个试点

---

## 1. 模块定位与边界

**合规审批模块（Compliance Approval Service, CAS）** 是 SkyMaster v2.0 的独立微服务，负责：
- 统一飞行报备/审批的**抽象层**（业务代码不关心底层通道）
- 对接 UOM 云系统（授权前 Mock，授权后真实）
- 属地公安通道 RPA（南宁试点）
- 审批状态订阅 + 回执归档 + 审计追溯

**明确不做的事**：
- ❌ 不做飞行任务本身（由 Mission Service 负责）
- ❌ 不做实名登记（由用户体系 + UOM 独立完成）
- ❌ 不做适飞空域查询（由 Airspace Service 负责，v2.1）

---

## 2. 架构总览

```
┌───────────────────────────────────────────────────────┐
│                Mission Service (v0.5)                 │
│  create_mission() → validate() → **approve()** ← 新增 │
└──────────────────────────┬────────────────────────────┘
                           │ gRPC: SubmitApproval
                           ▼
┌───────────────────────────────────────────────────────┐
│         Compliance Approval Service (CAS)             │
│  ┌────────────────┐  ┌────────────────┐              │
│  │ Approval Core  │  │ Channel Router │              │
│  │ · 状态机       │  │ · 通道选择     │              │
│  │ · 幂等锁       │  │ · 失败降级     │              │
│  │ · 回执归档     │  │ · 兜底人工     │              │
│  └───────┬────────┘  └───────┬────────┘              │
│          │                   │                       │
│          └──────┬────────────┘                       │
│                 ▼                                    │
│         ┌───────────────┐                            │
│         │Channel Adapter│  (统一 Interface)          │
│         │ Interface     │                            │
│         └───────┬───────┘                            │
│    ┌────────┬──┴──────┬───────────────┐              │
│    ▼        ▼         ▼               ▼              │
│┌───────┐┌───────┐┌────────────┐┌──────────────┐     │
││UOM    ││UOM    ││Nanning RPA ││Manual PDF    │     │
││Mock   ││Real   ││(公安五通道)││Fallback      │     │
││Adapter││Adapter││Adapter     ││Adapter       │     │
│└───────┘└───────┘└─────┬──────┘└──────────────┘     │
│                        │                             │
│                        ▼                             │
│                 ┌──────────────┐                     │
│                 │RPA Executor  │                     │
│                 │(Playwright + │                     │
│                 │ 邮件 SMTP +  │                     │
│                 │ 微信 API)    │                     │
│                 └──────────────┘                     │
└───────────────────────────────────────────────────────┘
             │
             ▼
    ┌────────────────┐
    │  PostgreSQL    │
    │  Redis (Lock)  │
    │  MinIO (回执)  │
    └────────────────┘
```

**核心设计原则**：
1. **Adapter Pattern**：Mock → Real 无缝切换，业务代码零改动
2. **状态机驱动**：draft → submitted → pending → approved/rejected → notified
3. **幂等强制**：同一 mission_id + 同一 channel 只能提交一次（Redis 分布式锁）
4. **人工兜底**：任何 Adapter 失败 3 次自动降级到 ManualPDFAdapter（生成 PDF 让律师/合规员线下办）

---

## 3. 数据模型

```sql
-- 审批申请主表
CREATE TABLE approval_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id     UUID NOT NULL REFERENCES missions(id),
    org_id         UUID NOT NULL,
    channel        VARCHAR(30) NOT NULL,  -- 'uom_mock'|'uom_real'|'nanning_rpa'|'manual_pdf'
    channel_ref    VARCHAR(120),          -- 通道方给的单号（UOM 申请编号 / 公安受理号）
    payload        JSONB NOT NULL,        -- 提交时的完整快照
    status         VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- draft/submitted/pending/approved/rejected/expired/canceled/error
    submitted_at   TIMESTAMPTZ,
    approved_at    TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ,           -- 批复有效期
    reject_reason  TEXT,
    retries        SMALLINT DEFAULT 0,
    created_by     UUID REFERENCES users(id),
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (mission_id, channel)          -- 幂等约束
);

CREATE INDEX ON approval_requests (org_id, status);
CREATE INDEX ON approval_requests (channel, submitted_at DESC);

-- 状态变更事件（审计 + 回放）
CREATE TABLE approval_events (
    id         BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES approval_requests(id),
    from_state VARCHAR(20),
    to_state   VARCHAR(20) NOT NULL,
    actor      VARCHAR(60) NOT NULL,   -- 'system'|'user:xxx'|'channel:uom'
    payload    JSONB,
    ts         TIMESTAMPTZ DEFAULT now()
);

-- 通道回执附件
CREATE TABLE approval_receipts (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES approval_requests(id),
    kind       VARCHAR(20) NOT NULL,   -- 'submit_ack'|'approval_pdf'|'reject_note'|'reminder'
    minio_key  TEXT NOT NULL,
    mime       VARCHAR(60),
    sha256     CHAR(64),
    received_at TIMESTAMPTZ DEFAULT now()
);

-- RPA 任务执行记录
CREATE TABLE rpa_runs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES approval_requests(id),
    scenario   VARCHAR(60) NOT NULL,   -- 'nanning_zhi_an'|'nanning_paichusuo'|'nanning_wexin'
    status     VARCHAR(20) NOT NULL,   -- 'queued'|'running'|'success'|'failed'
    started_at TIMESTAMPTZ,
    ended_at   TIMESTAMPTZ,
    screenshot_keys TEXT[],            -- MinIO 截图链
    logs       TEXT,
    error      TEXT
);
```

---

## 4. 状态机

```
              submit                approve              notify
    draft ──────────▶ submitted ──────────▶ approved ──────────▶ notified
      │                  │                     │                    │
      │                  │  reject             │  expire            │
      │                  ├─────────▶ rejected  ├─────────▶ expired  │
      │                  │                     │                    │
      │                  │  timeout            │                    │
      │                  ├─────────▶ pending   │                    │
      │  cancel          │  (人工介入)          │                    │
      ▼                  ▼                     ▼                    ▼
    canceled           canceled              canceled            canceled

  任何状态遇通道错误 → error （可 retry 回 submitted，或降级到 manual_pdf）
```

**状态迁移强制规则**：
- 只能沿有向边前进，禁止跨状态跳跃
- 每次迁移必须写 `approval_events`
- `approved → running_mission`：由 Mission Service 反向订阅事件驱动

---

## 5. Adapter Interface（Python 契约）

```python
# core/compliance/adapters/base.py
from typing import Protocol, Literal
from datetime import datetime
from pydantic import BaseModel

class ApprovalPayload(BaseModel):
    """通道无关的标准载荷"""
    mission_id: str
    org_id: str
    drone_sn: str
    operator_name: str
    operator_phone: str
    operator_id_card: str            # 敏感字段，Adapter 内部脱敏
    waypoints: list[dict]            # [{lat,lng,alt}]
    start_time: datetime
    end_time: datetime
    max_altitude_m: float
    max_speed_ms: float
    purpose: str                     # '巡检'|'测绘'|'表演'...
    scene: str                       # '适飞区'|'管制区'|'临时管制'
    attachments: list[str] = []      # MinIO keys

class SubmitResult(BaseModel):
    channel_ref: str                 # 通道回单号
    submitted_at: datetime
    receipt_keys: list[str] = []     # 保存到 MinIO 的回执

class ChannelAdapter(Protocol):
    channel_name: str

    async def submit(self, payload: ApprovalPayload) -> SubmitResult: ...
    async def query_status(self, channel_ref: str) -> Literal[
        "pending", "approved", "rejected", "expired"
    ]: ...
    async def fetch_receipt(self, channel_ref: str) -> bytes | None: ...
    async def cancel(self, channel_ref: str) -> bool: ...
```

---

## 6. 三大 Adapter 实现要点

### 6.1 UOMMockAdapter（v2.0-M1，2 周内）

**目的**：完全按 UOM 云系统接入规范设计的假接口，让业务先跑起来。

**实现**：
- 用 FastAPI 起独立 Mock 服务 `mock-uom:8100`
- 内置固定审批规则：
  - 适飞区 + 高度 ≤ 120m → 30 秒后自动 approved
  - 管制区 → 5 分钟后自动 pending，需人工在 admin 后台点通过
  - 高度 > 120m + 无 AOC → 立即 rejected
- 生成假 PDF 回执（含 mission_id 二维码）存入 MinIO
- **数据字段与真实 UOM 规范 1:1**，切换真实 Adapter 时 payload 结构零改动

### 6.2 UOMRealAdapter（v2.0-M6+，授权到位后）

**依赖**：需先拿到 AK/SK + 沙箱环境。

**实现要点**：
- HTTPS + 双向 TLS + 请求签名（HMAC-SHA256）
- 心跳保活（每 60s /heartbeat）
- 事件订阅走 UOM 提供的 MQ（可能是 Kafka 或 RocketMQ，以官方为准）
- 关键字段映射表见 §9

### 6.3 NanningRPAAdapter（v2.0-M2 起）

**五通道路由**：
```python
class NanningRPAAdapter:
    async def submit(self, payload):
        route = self._route(payload)
        # route 决策优先级：
        # 1. 大型活动/表演 → nanning_wechat (警务微信)
        # 2. 政府/国企       → nanning_oa      (公安内网 OA)
        # 3. 个人/小企业     → nanning_12345   (12345 政务热线)
        # 4. 常规重点区域    → nanning_zhi_an  (治安支队窗口 · 需邮件+电话)
        # 5. 兜底           → nanning_paichusuo (属地派出所窗口 · 需现场)
        return await route.execute(payload)
```

**RPA 技术栈**：
- **Playwright**：浏览器自动化（政务网 OA / 微信平台）
- **wxauto/itchat**：警务微信登记（走个人号，需值守账号）
- **SMTP + Excel 模板**：治安支队邮件报备（含 pdf 附件）
- **12345 API**：官方对外提供简单接口（需实名申请）
- **人工回退**：派出所窗口 → 生成 PDF 让运营人员现场跑

**RPA 稳定性策略**：
- 每次执行前用 headless=false 截图存 MinIO，失败方便定位
- 关键 selector 走"页面 hash + 文本双锚定"避免选择器漂移
- 失败重试 3 次，最终失败 → 降级到 ManualPDFAdapter

### 6.4 ManualPDFAdapter（兜底）

- 生成规范化的《飞行报备申请书》PDF
- 走飞书 / 邮件推送给合规员，附二维码回单入口
- 合规员线下办完后扫码上传批复 PDF，Adapter 状态推 approved
- **是 v2.0 上线时任何未覆盖场景的最后一道防线**

---

## 7. 接口设计

### 7.1 REST · `/api/v2/approvals`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/` | 创建审批申请（幂等：`Idempotency-Key` header） |
| GET  | `/` | 列表 · `?mission_id=&status=&channel=` |
| GET  | `/{id}` | 详情（含 events + receipts） |
| POST | `/{id}/submit` | 提交到通道（幂等锁 Redis 5min） |
| POST | `/{id}/cancel` | 取消（仅 draft/submitted/pending） |
| POST | `/{id}/retry` | 重试 · 仅 error 状态可用 |
| POST | `/{id}/downgrade` | 强制降级到 ManualPDFAdapter |
| GET  | `/{id}/receipts/{rid}` | 下载回执 |
| POST | `/{id}/manual-callback` | 兜底手动回填批复（合规员用） |

### 7.2 WebSocket

```
/ws/approvals/{org_id}   审批状态变更推送
```

消息格式：
```json
{
  "type": "approval_status_change",
  "request_id": "uuid",
  "mission_id": "uuid",
  "from": "submitted",
  "to": "approved",
  "channel_ref": "UOM202607091234",
  "ts": "2026-07-09T10:00:00Z"
}
```

### 7.3 gRPC · Mission Service 内部调用

```proto
service ComplianceService {
  rpc SubmitApproval(SubmitApprovalReq) returns (SubmitApprovalResp);
  rpc QueryApproval(QueryApprovalReq) returns (Approval);
  rpc SubscribeStatus(SubscribeReq) returns (stream StatusEvent);
}
```

---

## 8. 幂等与并发控制

**关键场景**：同一 mission_id 用户误点 3 次「提交报备」

```python
# core/compliance/service.py
async def submit(mission_id: str, channel: str) -> ApprovalRequest:
    lock_key = f"compliance:submit:{mission_id}:{channel}"
    async with redis_lock(lock_key, timeout=300):  # 5min
        # 1. 检查 DB 是否已存在同 (mission_id, channel) 的记录
        existing = await db.get_by(mission_id=mission_id, channel=channel)
        if existing and existing.status in ("submitted", "pending", "approved"):
            return existing  # 幂等返回
        # 2. 状态机流转
        request = await db.create_or_update(...)
        await state_machine.transit(request, "submitted")
        # 3. 调用 Adapter
        adapter = get_adapter(channel)
        result = await adapter.submit(request.payload)
        await db.attach_channel_ref(request.id, result.channel_ref)
        return request
```

**分布式锁选型**：Redis `SET NX EX`，用 `redis-py` 官方 `Lock`。

---

## 9. UOM 字段映射表（关键）

| 内部 payload | UOM 云系统字段（预期） | 备注 |
|---|---|---|
| `mission_id` | `applicationId` | 内部 UUID → 外部单号绑定 |
| `drone_sn` | `uasId` | UOM 实名登记 ID |
| `operator_id_card` | `operatorIdNo`（脱敏后前 6 + 后 4） | 传输加密 |
| `waypoints[].lat/lng` | `route[]` (WGS84) | 坐标系强制 WGS84 |
| `max_altitude_m` | `maxAlt` (m) | AGL |
| `max_speed_ms` | `maxSpeed` (m/s) | — |
| `start_time`/`end_time` | `startTime`/`endTime` (ISO8601 UTC) | UOM 用 UTC |
| `purpose` | `flightPurpose`（枚举） | 见 UOM 附录 A 枚举表 |
| `scene` | `airspaceType` | `SUITABLE`/`CONTROLLED`/`RESTRICTED` |

⚠️ 具体字段以获得授权后拿到的 UOM 正式 API 文档为准，Mock Adapter 内部保持向前兼容。

---

## 10. 12 周 Sprint 拆解

| Week | 任务 | 交付 |
|---|---|---|
| W1 | DB schema + 状态机 + Adapter Interface | 单测通过 |
| W2 | UOMMockAdapter + REST 骨架 | Mock 端到端跑通 |
| W3 | ApprovalService 幂等 + 事件流 | 3 次误点只入 1 单 |
| W4 | 前端审批中心页面（列表/详情/时间轴） | UI 与 Mock 联调 |
| W5 | NanningRPAAdapter 骨架 + Playwright 12345 通道 | 单跑通 12345 |
| W6 | 治安支队邮件通道 + 微信通道 | 3 通道全跑通 |
| W7 | ManualPDFAdapter + 飞书通知集成 | 降级兜底可用 |
| W8 | Mission Service 集成 gRPC + 状态回订阅 | 端到端串通 |
| W9 | 授权申请材料递交（Track A1 并行） | 材料齐 |
| W10 | 南宁 3 家试点客户 POC 上线 | Alpha 验证 |
| W11 | 压测 + 稳定性调优 + 审计合规检查 | 100 并发通过 |
| W12 | v2.0 Track A 发布 + 复盘报告 | 首个签单客户 |

---

## 11. 风险与对策

| 风险 | 概率 | 对策 |
|---|---|---|
| UOM 授权不到位 → 只能用 Mock | 高 | Mock Adapter 是完整业务闭环，客户可先跑试点 |
| RPA 选择器漂移导致失败率高 | 中 | 双锚定 + 每次截图 + 自动降级 ManualPDF |
| 微信通道封号 | 中 | 分离出独立值守账号 + 每日轮换 + 频率限制 |
| 12345 API 未开放个人使用 | 中 | 走客户主体名义调用 · 或 fallback Playwright |
| 敏感字段（身份证/位置）合规风险 | 高 | 落库前脱敏 + 传输 TLS + AuditLog 全记录 |
| 状态机并发死锁 | 低 | Redis Lock + DB 唯一约束双保险 |

---

## 12. 遗留待办

- [ ] UOM 授权代理公司询价（预算 30-100 万，Track A1）
- [ ] 南宁 3 家试点客户合同（Track A3）
- [ ] 12345 政务热线 API 申请材料
- [ ] 治安支队邮件报备模板法务审核
- [ ] 微信值守账号采购 + 合规评估

---

**文档负责人**：合规架构组
**版本**：v0.1-draft · 2026-07-09
**下一步**：SDD_v2.0_B_VisionAI.md（视觉 AI 5 模型技术方案） → SDD_v2.0_C_Copilot.md（Agent + 审批门禁）🐈
