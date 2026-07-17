# SkyMaster · v2.0 Track B R21 Step D · Vision WebSocket 流

> 2026-07-10 14:55 UTC · 视频流 WS 推流 + bbox overlay 落地

---

## ✅ 后端 · 发布侧

### `app/services/vision_stream.py`（新增）
- 通道命名：`vision.frame.all`（全局）+ `vision.frame.<drone_id>`（单机）
- `build_frame_payload(...)` — 组装 JSON 信封（type/runtime/model_tag/latency/detections/persisted_ids/GPS）
- `publish_vision_frame(...)` — 双通道 Redis publish，**永不抛异常**
- 图像不进 WebSocket — 只送 bbox + label，前端叠到本地视频画面上

### `app/api/v1/vision_copilot.py`
- `/vision/infer` DB commit 后 fan-out：
  ```python
  await publish_vision_frame(request.app.state.redis, payload, drone_id=...)
  ```
- Redis 挂掉 → API 仍然返回 200（推理不能被消息总线阻塞）

### `app/api/v1/websocket.py`（新增两个端点）
- `GET /api/v1/ws/vision/{drone_id}` — 单机流
- `GET /api/v1/ws/vision`             — 全机队流
- 复用 telemetry 的 `_pump_pubsub` + `_heartbeat` + JWT `?token=` 认证 + WS 计数

---

## ✅ 前端 · 订阅侧

### `lib/useVisionStream.ts`（新增 React Hook）
- 自动重连（capped 指数退避，最长 30 s）
- localStorage `token` 自动附加到 WebSocket URL
- 环形缓冲 30 帧 · 保留 `latest` 引用给 Canvas overlay
- 支持全局或单机模式：`useVisionStream()` / `useVisionStream(droneId)`

### `components/BBoxOverlay.tsx`（新增 Canvas 组件）
- 640×360 默认画布（可配置）
- 按 label 上色（person/vehicle/fire/smoke/... 各家不同）
- 标签胶囊显示 `label conf%`
- `minConfidence` 参数过滤低置信度检测
- 归一化坐标输入 → 无需知道原图分辨率

### `app/dashboard/vision/page.tsx`
新增 "🎬 实时视频流叠加" 卡片：
- 连接状态徽章（●已连接 / ○未连接）
- 缓冲帧数 + 最近一帧 runtime/latency/count
- 640×360 Canvas overlay + 最近 5 个目标列表

---

## 测试统计

| 步骤 | 用例数 | 累计 |
|---|---|---|
| R21 A (ONNX) | +9 | 187 |
| R21 B (Bus) | +10 | 197 |
| R21 C (LLM) | +11 | 208 |
| **R21 D (WS)** | +8 | **216** |

**216 pass · 8 skipped · tsc 0 error**

### R21 D 8 用例
- 3 纯 stream 单测（channel_for_drone / build_frame_payload / redis-none）
- 3 publish 行为（双通道 / 仅全局 / redis 抛异常吞掉）
- 2 端到端（/infer 触发 publish · redis 挂掉不影响 200）

---

## 数据流全景

```
┌──────────────┐   POST /vision/infer   ┌──────────────┐
│  Frontend    │──────────────────────▶│  FastAPI     │
│  (POST)      │                        │  vision      │
└──────────────┘                        │  runtime     │
                                        │  (mock/onnx) │
                                        └──────┬───────┘
                                               │ detections
                                               ▼
                                        ┌──────────────┐
                                        │  Redis PUB   │
                                        │  vision.     │
                                        │  frame.*     │
                                        └──────┬───────┘
                                               │ SUB
                     ┌─────────────────────────┴─────────────────────────┐
                     ▼                                                   ▼
              ws://.../ws/vision                        ws://.../ws/vision/{drone_id}
                     │                                                   │
                     ▼                                                   ▼
          ┌──────────────────┐                              ┌──────────────────┐
          │  ops-center wall │                              │  fleet dashboard │
          │  (全机队)         │                              │  (单机)          │
          └──────────────────┘                              └──────────────────┘
```

---

## 无侵入原则贯彻

- 未修改任何 R20/R21 A/B/C 的表结构、API 契约
- Redis 挂掉 → /vision/infer 仍然 200
- 前端未连 WS → 页面其他功能完全正常
- 图像不走 WS — 只送 bbox meta，带宽 < 1 KB/frame

---

## 下一根桩候选

| # | 方向 | 说明 |
|---|---|---|
| **E** | 切 Track A · Approval-as-a-Service | 反向对外 API（政府对接） |
| **F** | 切 Track D 收官 · SM2 数字签名 | 抗抵赖（对接商密） |
| **G** | Copilot 多轮上下文 | 会话内引用前 turn 的实体 |
| **H** | Vision 从 WebRTC 流入 | 直接对接 RTMP/RTSP 转码 → 推理 |

🐈 v2.0 · Track B R21 D 完成
