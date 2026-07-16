# SkyMaster v2.0 · Track B Vision AI SDD

- **版本**：v0.1-draft · 2026-07-09
- **对齐**：PRODUCT_SPEC §3.16 / v2.0 Roadmap Track B
- **目标**：3 个月内交付 5 个开箱即用的 Vision AI 内置模型 + 统一推理服务

---

## 1. 5 个内置模型清单

| # | 模型 | 场景 | 精度目标 | 推理速度目标 | 训练数据来源 |
|---|---|---|---|---|---|
| M1 | **车牌识别 LPR** | 停车场/交通 | mAP50 ≥ 0.85 | 30 FPS @ 1080p | CCPD 开源集 + 自采 1万 |
| M2 | **人脸合规打码** | 直播/媒体资产脱敏 | Recall ≥ 0.98 | 15 FPS @ 1080p | WIDER FACE + 自采 |
| M3 | **输电线巡检** | 电力/绝缘子/断股 | mAP50 ≥ 0.80 | 10 FPS @ 4K | Insulator-Defect 公开集 + 客户脱敏样本 |
| M4 | **光伏板缺陷** | 农光/牧光/工商业 | mAP50 ≥ 0.82 | 20 FPS @ 4K 热成像 | SolarELEB + 自建 |
| M5 | **水体污染检测** | 河湖/水库巡检 | IoU ≥ 0.75 | 5 FPS @ 4K | 卫星影像 + 定制 |

**5 个的选型逻辑**：
- **M1 车牌 + M2 人脸**：直接对应「等保 + 数据合规」硬需求，任何客户都要
- **M3 输电线**：国网/南网存量千亿级市场
- **M4 光伏板**：新能源风口，甘孜/阿坝节能项目直接落地（对齐用户 MEMORY 中的高校节能降碳项目）
- **M5 水体**：应急/环保部门 · 差异化竞品覆盖

---

## 2. 架构总览

```
┌────────────────────────────────────────────────────────────┐
│               Web Console / Mission Service                │
│  用户在任务规划中勾选「启用 AI · 车牌+输电线」               │
└──────────────────────┬─────────────────────────────────────┘
                       │ REST/gRPC
                       ▼
┌────────────────────────────────────────────────────────────┐
│              Vision AI Gateway (v2.0)                      │
│  · 模型注册中心       · 请求路由                            │
│  · 计费/配额         · 结果缓存                             │
│  · 版本/AB 测试       · 审计日志                            │
└──────┬───────────────────────────────────────┬─────────────┘
       │                                       │
       │ 分派                                  │ 落盘
       ▼                                       ▼
┌──────────────┐   ┌──────────────┐    ┌─────────────┐
│Realtime      │   │Batch         │    │Result Store │
│Inference     │   │Inference     │    │· PG 元数据  │
│(流式帧队列)  │   │(任务队列)    │    │· MinIO 图像 │
│Triton Server │   │Celery + GPU  │    │· TS 时序    │
└──────┬───────┘   └──────┬───────┘    └─────────────┘
       │                  │
       └────────┬─────────┘
                ▼
      ┌──────────────────┐
      │ Model Zoo (MinIO)│
      │ ├─ lpr/v1.onnx   │
      │ ├─ face/v1.onnx  │
      │ ├─ powerline/... │
      │ ├─ solar/...     │
      │ └─ water/...     │
      └──────────────────┘

       视频/图像来源：
       · MediaMTX (实时流)
       · Mission MediaAsset (历史资产)
```

---

## 3. 推理服务选型：Triton Inference Server

**为什么选 Triton**：
- 多框架支持（ONNX/TensorRT/PyTorch/TF/Python backend）
- 动态 batching + 模型热更新 + 版本管理
- Prometheus 指标原生输出
- GPU 利用率高（vs FastAPI 直接跑 pt）
- **HTTP + gRPC 双协议**，Gateway 只需一个客户端

**部署形态**：
- **Realtime 节点**：GPU 常驻 · Triton + 5 模型全部加载 · 显存 ≈ 8-12GB
- **Batch 节点**：可弹性伸缩 · Celery Worker + Triton client · 大任务分片

**模型格式统一**：
- 训练完 → 导出 ONNX → TensorRT FP16 优化（RTX 5070 及以上）
- CPU-only 环境 → OpenVINO IR（M5 水体推理可在 CPU 上跑）

---

## 4. 数据模型

```sql
-- 模型注册表
CREATE TABLE ai_models (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code           VARCHAR(40) UNIQUE NOT NULL,  -- 'lpr'|'face'|'powerline'|'solar'|'water'
    name           VARCHAR(120) NOT NULL,
    version        VARCHAR(20)  NOT NULL,        -- 'v1.0.0'
    task_type      VARCHAR(20)  NOT NULL,        -- 'detect'|'segment'|'classify'
    triton_model   VARCHAR(80)  NOT NULL,        -- Triton 内的 model_name
    input_shape    JSONB,                        -- {"C":3,"H":640,"W":640}
    labels         JSONB,                        -- ["car","truck",...]
    metrics        JSONB,                        -- {"mAP50":0.85, ...}
    minio_key      TEXT NOT NULL,
    sha256         CHAR(64),
    license        VARCHAR(40)  NOT NULL,        -- 'MIT'|'Apache2.0'|'Commercial'
    price_cent     INT DEFAULT 0,                -- 0 = 免费内置
    published_at   TIMESTAMPTZ,
    deprecated     BOOLEAN DEFAULT false
);

-- 推理任务
CREATE TABLE inference_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    model_code   VARCHAR(40) NOT NULL,
    model_version VARCHAR(20),
    mode         VARCHAR(20) NOT NULL,       -- 'realtime'|'batch'
    source_type  VARCHAR(20),                -- 'stream'|'file'|'mission'
    source_ref   TEXT,                       -- rtsp url / minio key / mission_id
    status       VARCHAR(20) DEFAULT 'queued',
    total_frames INT,
    done_frames  INT DEFAULT 0,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error        TEXT,
    created_by   UUID,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- 检测结果时序表（TimescaleDB hypertable）
CREATE TABLE detections (
    time        TIMESTAMPTZ NOT NULL,
    job_id      UUID NOT NULL,
    drone_id    UUID,
    frame_idx   INT,
    label       VARCHAR(40),
    confidence  REAL,
    bbox        JSONB,                       -- {x,y,w,h} 归一化
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    alt         REAL,
    thumb_key   TEXT                         -- MinIO 缩略图
);
SELECT create_hypertable('detections', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON detections (job_id, time DESC);
CREATE INDEX ON detections (label, time DESC) WHERE confidence >= 0.7;
```

---

## 5. 接口设计

### 5.1 REST · `/api/v2/vision`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/models` | 列出可用模型 · `?task_type=&license=` |
| GET  | `/models/{code}` | 模型详情（含 metrics/labels） |
| POST | `/jobs` | 创建推理任务（realtime/batch） |
| GET  | `/jobs` | 任务列表 · 分页 |
| GET  | `/jobs/{id}` | 任务详情（含进度） |
| POST | `/jobs/{id}/cancel` | 取消 |
| GET  | `/jobs/{id}/detections?from=&to=&label=&min_conf=` | 结果查询 |
| GET  | `/jobs/{id}/heatmap` | 检测热力图（Cesium 叠加） |
| POST | `/detect` | **单帧同步推理**（用于前端预览，轻量） |

**POST /jobs 请求示例**：
```json
{
  "model_code": "powerline",
  "model_version": "v1.0.0",
  "mode": "realtime",
  "source_type": "stream",
  "source_ref": "rtsp://mediamtx:8554/drone-001",
  "filters": {
    "labels": ["insulator_broken", "line_swing"],
    "min_confidence": 0.6
  },
  "actions": {
    "alert_on_detect": true,
    "save_thumbnail": true
  }
}
```

### 5.2 WebSocket · 实时检测推送

```
/ws/vision/jobs/{job_id}/detections   实时检测事件流
```

消息格式：
```json
{
  "type": "detection",
  "job_id": "uuid",
  "ts": "2026-07-09T10:00:00Z",
  "frame_idx": 1234,
  "detections": [
    {"label": "insulator_broken", "conf": 0.87, "bbox": {"x":0.3,"y":0.4,"w":0.05,"h":0.05}}
  ],
  "geo": {"lat": 22.8, "lng": 108.3, "alt": 45.2},
  "thumb_url": "https://.../thumbs/abc.jpg"
}
```

---

## 6. 关键数据流

### 6.1 实时流推理链路

```
Drone ──RTSP──▶ MediaMTX ──RTSP pull──▶ FFmpeg Frame Extractor
                                            │
                                            │ 640×640 归一化 · 每 3 帧抽 1
                                            ▼
                                        Triton HTTP
                                        model=powerline_v1
                                            │
                                     PostProcess (NMS)
                                            │
                                    ┌───────┴────────┐
                                    ▼                ▼
                          Redis Stream          TimescaleDB
                          detections:{job}      detections
                                    │
                                    ▼
                             WS Broadcaster
                                    │
                                    ▼
                          /ws/vision/jobs/{id}
```

**关键设计**：
- 帧抽样率可配（默认每 3 帧 1 次，10 FPS → 3.3 FPS 推理）
- NMS 阈值可 config
- 高置信度（≥0.7）自动写 Alert 表
- 缩略图 crop 出来后异步 upload MinIO

### 6.2 批处理链路

```
User: POST /jobs (mode=batch, source=mission_123)
             │
             ▼
      inference_jobs 入 Celery 队列
             │
             ▼
      Celery Worker (每 Worker 独占 1 GPU)
             │
       ┌─────┴──────┐
       │  分片      │
       │ (每 100 帧)│
       └─────┬──────┘
             ▼
       Triton batch=16
             ▼
        写 detections
             ▼
       更新 done_frames
             ▼
   done_frames == total → status=done → 飞书通知
```

---

## 7. 模型训练与迭代 Pipeline（Ops 视角）

```
数据采集 → 标注 (LabelStudio) → 数据版本 (DVC)
                                    │
                                    ▼
                             训练 (PyTorch)
                                    │
                                    ▼
                           验证集 metrics ≥ 阈值
                                    │
                                    ▼
                             ONNX Export
                                    │
                                    ▼
                          TensorRT FP16 优化
                                    │
                                    ▼
                          灰度发布 (10% 流量)
                                    │
                                    ▼
                    A/B 对比 3 天 → 全量或回滚
```

**模型版本策略**：
- 语义化版本：`major.minor.patch`
- 每模型至少保留 2 个版本可回滚
- 灰度策略在 Gateway 层实现（按 org_id % 100）

---

## 8. 硬件资源规划

| 部署形态 | GPU | CPU | 内存 | 说明 |
|---|---|---|---|---|
| 客户 POC（单机） | RTX 5070 12G | 8C | 32G | 5 模型任意 2 个同时 realtime |
| 小规模生产 | RTX 4090 24G × 1 | 16C | 64G | 5 模型全部 realtime + 少量 batch |
| 中规模生产 | RTX 4090 × 2 | 32C | 128G | 20+ 客户 + 弹性 batch |
| 大规模 SaaS | A100 40G × 4+ | 64C | 512G | 单集群 100+ 客户 |

**成本优化**：
- FP16 vs FP32 显存减半 · 精度损失 <1%
- INT8 量化 → 后续 v2.1 落地（针对边缘部署）
- 客户拒绝上云的场景 → Jetson Orin NX 边缘盒方案（v2.3）

---

## 9. 12 周 Sprint 拆解

| Week | 任务 | 交付 |
|---|---|---|
| W1 | Triton Server 部署 + Model Zoo 结构 | 5 个模型占位符能加载 |
| W2 | Gateway 骨架 + `/models` `/detect` 单帧 | Postman 能跑单张图 |
| W3 | M1 车牌模型（用 CCPD 微调 YOLOv8） | mAP50 ≥ 0.85 |
| W4 | M2 人脸打码（用 WIDER FACE） | Recall ≥ 0.98 |
| W5 | 实时流 pipeline（FFmpeg + Triton + WS） | 端到端跑通 |
| W6 | M3 输电线模型 + 客户脱敏数据训练 | Alpha 版 |
| W7 | 批处理 pipeline（Celery + 分片） | 1 小时视频能跑完 |
| W8 | M4 光伏板模型 + 热成像预处理 | Alpha 版 |
| W9 | M5 水体污染分割模型 | Alpha 版 |
| W10 | 前端页面（模型市场 / 任务详情 / 热力图） | UI 完整 |
| W11 | 灰度/AB 测试 + Prometheus 指标 | Ops 完备 |
| W12 | v2.0 Track B 发布 · 至少 3 客户使用 | 达成验收 |

---

## 10. 风险与对策

| 风险 | 概率 | 对策 |
|---|---|---|
| 客户脱敏数据不足 → 模型精度打不上去 | 高 | 先用开源集打样，客户签约后合作训练 |
| GPU 显存不足 → 5 模型不能全加载 | 中 | 冷模型 unload · LRU 换出 |
| TensorRT 版本兼容性坑 | 中 | 固定 TRT 版本 · Docker 镜像统一 |
| 实时 pipeline 帧丢失 | 中 | Redis backpressure · 优雅降级到关键帧 |
| 人脸模型隐私合规 | 高 | 模型 output 只出 bbox 不出 embedding · 数据不出域 |

---

## 11. 与 Track A（合规）联动

**关键场景**：AI 检测到「未报备飞行」→ 自动触发报备提醒

```python
# 伪代码：Vision Alert Hook
async def on_detection(det):
    if det.label == "unauthorized_drone" and det.confidence > 0.8:
        # 反向调用 ComplianceService
        await compliance.check_approval(det.drone_id)
        if not approved:
            await alerts.raise("发现未报备飞行", geo=det.geo)
```

---

**文档负责人**：AI 架构组
**版本**：v0.1-draft · 2026-07-09
**下一步**：SDD_v2.0_C_Copilot.md（Agent + 审批门禁 + Trace）🐈
