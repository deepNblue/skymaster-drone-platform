# 南宁 12309 无人机防控作战视图

把平台已有能力按检察服务中心辖区编排成一个可汇报、可追溯的场景视图：
**巡逻航线 → 机队态势 → 视觉告警 → 视频回传 → 飞行审批 → 取证归档 → 态势时间线**。
本视图不重写任何业务逻辑，只做聚合与呈现。

## 配置驱动

场景定义：`backend/config/scenarios/12309.json`。可用 `SCENARIO_12309_CONFIG` 环境变量覆盖路径。

| 配置块 | 作用 |
|---|---|
| `region` | 辖区名称、bbox、中心点、限高（150m），用于告警/审批归属判定与展示 |
| `scope` | 航线 ID 前缀、机体标签关键字、机体 SN、取证场景名称关键字，定义「哪些数据属于 12309」 |
| `windows` | 告警时窗（默认 24h）、列表上限、时间线条数 |
| `severity_rules` | 置信度 → 告警等级映射（默认 ≥0.85 高危、≥0.60 关注、其余一般） |
| `approval_status_map` / `approval_open_statuses` | 审批状态归一化与「审批中」口径 |
| `alert_open_statuses` | 待处置告警口径 |
| `kpis` | 首页 KPI 卡片的 key、标签、单位，前端按配置渲染 |

新增场景只需在 `config/scenarios/` 放一个 JSON，不改代码。

## 聚合端点

| 方法 + 路径 | 说明 |
|---|---|
| `GET /api/v1/scenarios` | 可用场景列表（从配置目录扫描） |
| `GET /api/v1/scenarios/12309/overview` | 场景态势全量聚合 |

需要 Bearer 认证。响应结构：

```json
{
  "meta": {"id": "12309", "region": {...}, "kpis": [...]},
  "routes": {"available": true, "count": 3, "items": [...]},
  "fleet":  {"available": true, "items": [...]},
  "missions": {"available": false, "reason": "DJI 连接器未挂载…", "items": []},
  "alerts": {"available": true, "window_minutes": 1440, "items": [...]},
  "approvals": {"available": true, "items": [...]},
  "streams": {"available": false, "reason": "视频流服务不可用…", "items": []},
  "evidence": {"available": true, "items": [...]},
  "kpi": {"fleet_online": 1, "open_alerts": 2, ...},
  "timeline": [{"kind": "approval", "at": "...", "title": "..."}],
  "generated_at": "..."
}
```

每个数据块独立 `try/except`：MediaMTX 不可用、DJI 连接器未挂载、某张表查询失败，
都只让对应块降级为 `available=false` 并给出 `reason`，整页仍返回 200。

## 数据来源与复用

| 块 | 来源 | 复用方式 |
|---|---|---|
| 巡逻航线 | `dji_mission_routes.json` | `DJICloudConnector.mission_routes()`；连接器缺失时直接读配置 |
| 机队 | `drones` 表 | 按 `org_id` 租户过滤，再按配置中的标签/SN 判定 12309 归属 |
| 飞行任务 | DJI 连接器内存 | `mission_status()`，按机队 SN 过滤 |
| 视觉告警 | `vision_detections` 表 | 按 `tenant_id` + 24h 时窗查询，bbox 内坐标过滤，置信度分级 |
| 飞行审批 | `flight_approvals` 表 | 按 `tenant_id` 查询，`area_polygon` 与辖区 bbox 相交判定 |
| 视频回传 | MediaMTX | `StreamManager.list_active_streams()` |
| 取证归档 | `scenes` 表 | 按 `org_id` 过滤，场景名称匹配配置关键字 |
| 时间线 | 上述结果二次组装 | 按时间倒序合并告警/审批/任务/取证事件 |

## 前端

`/dashboard/scenarios/12309`，导航「12309 防控」。顶部 KPI 卡片按 `meta.kpis` 渲染；
主体分区展示航线、任务与机队、告警、视频、审批、取证，底部为态势时间线。
默认 30 秒自动刷新，可手动关闭。视频区只提供跳转到 streams 播放页的入口，
不直接嵌 HLS，避免 Bearer token 无法随 `<video src>` 传递导致 401。

## 已知限制

- 审批状态枚举在历史数据里存在 `in_review` / `under_review` 混用，依赖 `approval_status_map` 归一化；新增枚举需同步配置
- `area_polygon` 判定采用「任一顶点落入 bbox」的近似规则，跨辖区大多边形可能漏判；精确判定需几何库支持
- 任务状态来自连接器进程内存，后端重启后为空；跨重启的任务态势仍需落库
- 取证归档按场景名称关键字归属 12309，未通过任务 ID 强关联；建议后续在 Scene 元数据中增加场景标签
- 视频流列表依赖 MediaMTX 在线；流播放页需要有效 Bearer token
