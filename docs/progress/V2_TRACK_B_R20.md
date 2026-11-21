# SkyMaster · v2.0 Track B R20 · Vision AI + Copilot Agent

> 2026-07-10 13:20 UTC · Track B 骨架落地
> 规格书 §3.7 (Vision AI) + §3.8 (Copilot Agent)

---

## 🎯 定位

**Vision AI Edge Runtime + Copilot Agent** — v2.0 两大 AI 底座之一
- 视觉：可插拔运行时（mock/onnx/triton/jetson），零 GPU 环境也能启动
- Copilot：**规则-first · LLM-optional** — 亚毫秒级意图解析，热路径零成本

---

## ✅ 后端六件套

### 1. 数据模型（Alembic 0014）
- `vision_detections` — tenant/drone/mission/stream/label/conf/bbox/GPS/frame_ts/model_tag/runtime/status/meta，6 索引
- `copilot_sessions_v2` — 与旧 `copilot_sessions` 表命名隔离，避免 v0.1 冲突
- `copilot_turns_v2` — user_text/intent/args/reply_text/tool_call/tool_result/latency_ms

### 2. Vision Runtime 抽象 `vision_runtime.py`
```python
class VisionRuntime(ABC):
    async def infer(image_bytes, *, frame_idx, hint) -> DetectionFrame

@register_runtime("mock")   # 默认：确定性合成检测（CI/dev）
@register_runtime("onnx")   # 生产：ONNX Runtime CPU/GPU
# triton / jetson 预留
```
- 环境变量 `VISION_RUNTIME` 切换
- `settings.vision_persist_threshold=0.65` — 低置信度只返回不落库
- 缺依赖时 **优雅降级 → mock**（永不炸请求）

### 3. Copilot 意图解析器 `copilot_intent.py`
Chinese/English 关键词 + 正则双路径：
| 触发 | 意图 | 提取参数 |
|---|---|---|
| 起飞 / takeoff | takeoff | — |
| 降落 / land | land | — |
| 返航 / rth | return_home | — |
| 悬停 / hover | hover | — |
| 去 30.5,104.06,120 | goto_waypoint | lat/lng/alt |
| 看到 person 吗 | vision_query | label |
| 开始录像 | start_recording | — |
| 生成报告 | generate_report | — |
| 状态 / 帮助 | status / help | — |

`run_turn(text, drone_id)` → 一次调用完成 parse + reply + plan
- 置信度 [0,1]：1.0 关键词、0.8 正则、0.0 未知
- 未知直接返回 `clarify` 提示语，不投喂 LLM（可选后续开启）

### 4. Copilot v0.1 兼容层 `copilot_agent.py`
恢复原 `CopilotAgent` / `VALID_INTENTS` 接口 · 支持 Anthropic 与 OpenAI 双 content shape · v0.1 测试 100% 通过

### 5. REST API 7 端点 `vision_copilot.py`
Vision：
- `GET  /vision/runtimes` — 列出可用运行时
- `POST /vision/infer` — 单帧推理（可选 base64 图像 + hint + GPS）
- `GET  /vision/detections` — 过滤（label/drone/mission/status/since_minutes）
- `POST /vision/detections/{id}/ack` — acknowledged/dismissed/escalated

Copilot：
- `POST /copilot/dry-run` — 意图预览（不落库，供 UI 输入提示）
- `POST /copilot/sessions` — 新建会话（operator/analyst/instructor）
- `GET  /copilot/sessions` — 列出（用户隔离）
- `GET  /copilot/sessions/{sid}/turns` — 会话回放
- `POST /copilot/sessions/{sid}/turns` — 发送指令

### 6. 权限隔离
所有 Copilot 会话按 `user_id` 隔离 · 跨用户读取返回 404

---

## ✅ 前端两件套

### `/dashboard/vision`
- 运行时状态卡（active + persist_threshold + available）
- 4 项统计（总数 / 高置信度 / 火灾-烟雾 / 车辆-船只）
- ⚡ 快速推理测试（发送合成帧 + hint）
- 🎯 检测事件流表格 · 按标签/状态过滤 · 一键 确认/升级/忽略

### `/dashboard/copilot-agent`
- 三栏布局：会话列表 + 对话流 + 输入框
- **实时意图预览** — 打字 250ms 防抖调 `dry-run`
- 意图彩色标签 · 工具调用面板 · latency 显示
- 三种 Persona（operator/analyst/instructor）
- 侧栏菜单集成

---

## 测试统计

```
Backend: 178 pass (+31 vision_copilot) / 8 skipped · 全绿
Frontend: tsc 0 error
```

**31 新增用例：**
- 4 Vision runtime 单元（注册表 / 确定性 / hint 偏置 / base64）
- 12 Intent 关键词（起飞/降落/返航/悬停/录像×2/报告/帮助/状态 · CN+EN）
- 6 Intent 结构（goto CN/EN + vision_query + unknown + empty + plan_tool_call）
- 2 render/run_turn
- 7 API 端点（runtimes / infer / infer+persist / dry-run / session-create / session-turns / 跨用户隔离）

---

## 表命名冲突处理

原 `copilot_sessions/turns` 表已存在（v0.1 · 20260709），新表用后缀 **`_v2`**：
- `copilot_sessions_v2` / `copilot_turns_v2` — v2.0 R20 结构
- Model 类改名 `CopilotSessionV2` / `CopilotTurnV2` — SQLAlchemy 注册表隔离
- 旧表继续供 v0.1 使用，无侵入

---

## 下一根桩候选

| # | 方向 | 说明 |
|---|---|---|
| **A** | Vision 实体接入 ONNX | 加载真 YOLOv9-s ONNX + 图像 IO + 预处理 |
| **B** | Copilot 工具执行闭环 | `execute=True` 时真的调 drone command bus |
| **C** | LLM fallback | 意图置信度 < 0.6 时走 llm_client 做 few-shot 分类 |
| **D** | 视频流 WS 推流识别 | streams.py 接检测 → WS push → 前端 overlay bbox |
| **E** | 切 Track A · Approval-as-a-Service | 反向对外 API |
| **F** | 切 Track D 收官 · SM2 数字签名 | 抗抵赖 |

🐈 v2.0 Track B · R20 骨架完备。可插拔运行时 + 规则-first Copilot 交付。
