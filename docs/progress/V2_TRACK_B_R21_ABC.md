# SkyMaster · v2.0 Track B R21 · A/B/C 三步落地

> 2026-07-10 14:35 UTC · Steps A + B + C 全部落地
> R21 = R20 骨架的三个纵深穿刺

---

## ✅ Step A · Vision 接入真 ONNX（YOLOv5/v8/v9 通吃）

### 生产就绪的 ONNX Runtime 后端
- **依赖新增**: `onnxruntime 1.27.0` + `numpy 2.4.6` + `Pillow 12.3.0`
- **算子**: CPU / CUDA 双执行器，检测到 CUDA 自动优先
- **配置** (env):
  - `VISION_ONNX_MODEL_PATH` — .onnx 文件路径
  - `VISION_ONNX_LABELS_PATH` — 可选类别文件（缺省 COCO-80）
  - `VISION_ONNX_CONF_THR=0.25` / `VISION_ONNX_IOU_THR=0.45` / `VISION_ONNX_IMGSZ=640`

### 完整推理管线
1. **Preprocessing**：letterbox → RGB → CHW float32 /255
2. **Shape-agnostic decoder** — 三种 YOLO 输出 layout 自动识别：
   - `(1, N, 4+1+C)` YOLOv5 raw
   - `(1, 4+C, N)` YOLOv8/v9 raw（自动转置）
   - `(1, N, 4+C)` YOLOv8 已转置
3. **Class-aware greedy NMS**（纯 numpy，无 torchvision 依赖）
4. **De-letterbox** 还原到原图坐标 → normalized [0,1] bbox

### 优雅降级
- 模型文件缺失 → `onnx-degraded` + mock 后端
- 图像为空 → `onnx-noimage` + mock
- 推理异常 → 单帧返空，不炸请求
- **异步执行** — `run_in_executor` 避免阻塞 event loop

### 测试 9 用例
- 4 个降级路径（缺模型 / 缺图 / 未知 shape / NMS 抑制）
- 3 个 YOLO layout 解码验证
- 1 个 preprocess shape+dtype+范围
- 1 个 custom labels

---

## ✅ Step B · Copilot execute=True 打通命令总线

### `copilot_bus.py` — 60 行的路由器
```python
_SIM_ROUTE = {
    "drone.command.takeoff":  ("arm",    None),
    "drone.command.land":     ("mode",   lambda a: {"mode": "hover"}),
    "drone.command.rth":      ("rtl",    None),
    "drone.command.hover":    ("mode",   lambda a: {"mode": "hover"}),
    "drone.command.goto":     ("goto",   lambda a: {"lat":..., "lng":..., "alt":...}),
    "mission.recording.*":    (None, None),    # planned, not wired
    "vision.detections.recent": (None, None),
    "agent.status":           (None, None),
}
```

### 三重安全防线
1. **角色门禁** — 仅 `operator` / `admin` 可执行，`viewer` 强制 `denied`
2. **端口解析** — `COPILOT_SIM_PORT_MAP` (JSON) → `SIM_DRONES` fallback → 无路由则报错
3. **结构化错误** — 网络/HTTP/超时都返回 `{status, detail}`，永不抛异常

### API 集成
`POST /copilot/sessions/{sid}/turns` 新增 `execute` 字段：
- `execute=false`（默认）→ 只规划，`tool_result=None`
- `execute=true` → 通过 bus 派发，`tool_result` 记录执行状态

Turn 表 `status` 字段联动：bus 报 `error`/`denied` 时同步覆盖 `ok`。

### 测试 10 用例
- 6 个纯 bus 单测（路由表 / 角色拒绝 / noop / planned / 无端口 / 不可达）
- 1 个 stub urlopen 验证 goto 的 URL + body 完整传参
- 3 个 API 端到端（execute=true 记录 / execute=false 保持 None / viewer 拒绝）

---

## ✅ Step C · LLM Fallback（意图置信度 < 0.6 时）

### `copilot_llm_fallback.py`
纯函数 `async fallback_parse(text, llm_client, ...)` — 完全解耦：
1. 先跑规则解析（`copilot_intent.parse_intent`）
2. **规则置信度 ≥ 阈值 → 直接返回**（大多数情况热路径零成本）
3. **fallback 未开启 → 直接返回**（默认 `COPILOT_LLM_FALLBACK=false`）
4. LLM 询问：严格 JSON `{intent, args}` prompt

### 强度约束
- **词汇表锁死** — LLM 输出必须在 12 个合法 intent 内，否则丢弃
- **args 类型强校验** — `goto_waypoint` 要求 `lat/lng` 可转 float，否则回退
- **JSON 提取容错** — 支持裸 JSON / \`\`\`json fence / 前后带 prose
- **超时 6s** — 超时视为失败，回退规则结果
- **异常永不外泄** — 记 `llm_error` 到 args，继续走原路径

### 配置
```env
COPILOT_LLM_FALLBACK=true             # 默认 false
COPILOT_LLM_FALLBACK_THRESHOLD=0.6
```

### 测试 11 用例
- 2 off-by-default 保护（关闭 / 高置信度绕过）
- 2 fallback 触发（普通 / code-fence / prose-wrapped）
- 2 goto_waypoint（args 强类型 / 缺 lat/lng 拒绝）
- 4 robust（LLM 抛异常 / 越界 intent / unparseable / no client）
- 1 vision_query args

---

## 测试统计对比

| 阶段 | 用例数 | 累计 |
|---|---|---|
| R20 骨架 | 178 | 178 |
| **R21 A** (ONNX) | +9 | 187 |
| **R21 B** (Bus) | +10 | 197 |
| **R21 C** (LLM) | +11 | **208** |

**208 pass · 8 skipped · 全绿 · tsc 0 error**

---

## 无侵入原则贯彻

- 三步没有修改任何 R20 之前的表结构 / API 契约
- LLM fallback 默认关闭，规则解析结果字节相同
- ONNX 后端未激活时（`VISION_RUNTIME=mock`）零 overhead
- Bus 未 `execute=true` 时零 HTTP 调用

---

## 下一根桩候选

| # | 方向 | 说明 |
|---|---|---|
| **D** | 视频流 WS 推流识别 | streams.py 接检测 → WS push → 前端 overlay bbox |
| **E** | 切 Track A · Approval-as-a-Service | 反向对外 API（政府对接） |
| **F** | 切 Track D 收官 · SM2 数字签名 | 抗抵赖（对接商密） |
| **G** | Copilot 多轮上下文 | 会话内引用前 turn 的实体（"再飞高 20m"） |

🐈 v2.0 · Track B R21 A/B/C 完成
