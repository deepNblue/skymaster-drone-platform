"""Official Playbook seed data for Copilot Workflow · T11.1 (v2.1 E2.2).

The engine (T10.x) is complete — now users need **seed content**. Three
official playbooks from the v2.0 roadmap:

  1. morning-inspection : 早查 · 每日启动清单
  2. emergency-response : 应急 · 告警响应模板
  3. compliance-patrol  : 合规巡查 · 定期审计

Each is a self-contained DSL string that references only tools shipped
in ``tool_registry.build_default_registry()`` — so they validate green
on a fresh install with no extra configuration.

Design notes
============
* Playbooks are **read-only** from the client's perspective — they
  don't live in ``copilot_workflows`` (which is per-org and mutable).
  Instead they're exposed via a dedicated ``/playbooks`` endpoint that
  serves this constant dict. Users can then "Save as..." to fork one
  into their own org, at which point the normal CRUD applies.
* We keep the YAML strings **short and heavily commented** — these are
  the first thing a new user sees, and the comments teach the DSL
  more effectively than any docs page.
* Each playbook has an ``inputs`` sample so the History/Editor UI can
  hydrate the "运行时输入 (JSON)" panel for one-click try-outs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Playbook:
    slug: str
    name: str
    description: str
    dsl_yaml: str
    sample_inputs: dict[str, Any]
    # T11.4: coarse-grained taxonomy so the picker UI can filter.
    # Keep the vocabulary small — 6 seed playbooks don't warrant a
    # multi-level tag tree yet. Convention: first tag is the primary
    # scenario ("ops"/"domain"), rest are secondary attributes.
    tags: tuple[str, ...] = ()


# ------------------------------------------------------------------------- #
# 1. Morning inspection · 早查                                              #
# ------------------------------------------------------------------------- #

_MORNING_YAML = """\
# 早查 Playbook — 每天上班第一件事:
#   1) 拉取本组织所有无人机列表 (含电量/位置)
#   2) 抓最近 60 分钟检测事件, 看有没有过夜异常
#   3) 查一下作业半径内的天气 (成都天府广场坐标, 需按驻地改)
version: "0.1"
name: "morning-inspection"
description: "早查 · 每日启动清单"
steps:
  # 拉取所有无人机, 后续步骤按 status='online' 过滤
  - id: fleet
    tool: list_drones
    args: {}

  # 最近一小时的检测事件 — 阈值放宽到 0.5, 让漏检更少
  - id: overnight_detections
    tool: list_detections
    args:
      since_minutes: 60
      min_confidence: 0.5
      limit: 50

  # 作业区域天气 — TODO 按你的驻地改坐标
  - id: weather
    tool: query_weather
    args:
      lat: 30.5728
      lng: 104.0668
"""

MORNING_INSPECTION = Playbook(
    slug="morning-inspection",
    name="早查 · 每日启动清单",
    description=(
        "拉取本组织无人机 + 检测过去 60 分钟事件 + 查作业区天气。"
        "适合班前 5 分钟走查。默认坐标为成都，请按驻地改 lat/lng。"
    ),
    dsl_yaml=_MORNING_YAML,
    sample_inputs={},
    tags=("ops", "readonly", "daily"),
)


# ------------------------------------------------------------------------- #
# 2. Emergency response · 应急                                              #
# ------------------------------------------------------------------------- #

_EMERGENCY_YAML = """\
# 应急 Playbook — 收到告警后 30 秒内做完:
#   1) 定位涉事无人机的实时状态
#   2) 拉最近半小时的高置信度检测, 判断是否已有目标
#   3) 生成一次场景巡查任务 (mission), 供指挥员一键派发
#
# 注意: create_mission 是 sensitive 工具, 会走 approval gate,
# 不会直接派发.
#
# 用户在编辑器里改 drone_id / waypoints 后再保存 fork.
version: "0.1"
name: "emergency-response"
description: "应急 · 告警响应模板"
steps:
  - id: target_drone
    tool: get_drone_status
    args:
      drone_id: "${input.drone_id}"

  # 只看高置信度事件, 避免误触发
  - id: recent_targets
    tool: list_detections
    args:
      drone_id: "${input.drone_id}"
      since_minutes: 30
      min_confidence: 0.75
      limit: 20

  # 生成任务草稿, 等指挥员审批后派发
  - id: draft_mission
    tool: create_mission
    args:
      name: "应急响应任务"
      drone_id: "${input.drone_id}"
      waypoints:
        - [30.5728, 104.0668, 100.0]
        - [30.5731, 104.0672, 120.0]
"""

EMERGENCY_RESPONSE = Playbook(
    slug="emergency-response",
    name="应急 · 告警响应模板",
    description=(
        "定位涉事无人机 + 拉近期高置信度检测 + 生成待审批的巡查任务。"
        "包含一个 sensitive 工具 (create_mission)，触发审批网关。"
        "使用前请在编辑器里替换 drone_id 和 waypoints。"
    ),
    dsl_yaml=_EMERGENCY_YAML,
    sample_inputs={
        "drone_id": "00000000-0000-0000-0000-000000000000",
    },
    tags=("ops", "sensitive", "incident"),
)


# ------------------------------------------------------------------------- #
# 3. Compliance patrol · 合规巡查                                           #
# ------------------------------------------------------------------------- #

_COMPLIANCE_YAML = """\
# 合规巡查 Playbook — 每周跑一次, 落审计:
#   1) 列出最近的飞行申请, 定位仍处 in_review 的 blocker
#   2) 拉最近 24 小时的检测事件, 汇总类别分布
#   3) 查已安装的 AI 模型清单 (合规审计要求可追溯)
#
# 100% 只读工具, 可以安全地定时自动跑.
version: "0.1"
name: "compliance-patrol"
description: "合规巡查 · 周度审计报表"
steps:
  - id: pending_approvals
    tool: list_approvals
    args:
      status: "in_review"
      limit: 20

  - id: detection_summary
    tool: detection_stats
    args:
      since_minutes: 1440  # 24 小时

  - id: installed_models
    tool: list_installed_models
    args: {}
"""

COMPLIANCE_PATROL = Playbook(
    slug="compliance-patrol",
    name="合规巡查 · 周度审计报表",
    description=(
        "列出待审批 + 24h 检测统计 + 已安装模型。"
        "100% 只读工具，可安全定时自动执行。"
    ),
    dsl_yaml=_COMPLIANCE_YAML,
    sample_inputs={},
    tags=("ops", "readonly", "audit"),
)


# ------------------------------------------------------------------------- #
# 4. Crop protection · 植保 (T11.3)                                         #
# ------------------------------------------------------------------------- #

_CROP_PROTECTION_YAML = """\
# 植保 Playbook — 药剂喷洒作业前的 30 秒准备:
#   1) 查作业地块的实时天气 (风速>4m/s 或降雨临近 → 不喷)
#   2) 检查空域, 避免误闯限飞区 (省界/机场/自然保护区)
#   3) 列出可派飞机, 挑电量>60% 的机
#   4) 生成喷洒任务草稿, 走审批
#
# 默认坐标为四川农业大学雅安校区试验田, 请按地块改.
version: "0.1"
name: "crop-protection"
description: "植保 · 药剂喷洒前置检查"
steps:
  # 关键决策点: 风速/降雨 -- 后续可加 on_failure 转人工判断
  - id: field_weather
    tool: query_weather
    args:
      lat: 29.9833
      lng: 102.9917

  # 检查地块所在空域, 拉一个 500m x 500m 的方框
  - id: airspace_check
    tool: check_airspace
    args:
      geo:
        - [102.9910, 29.9825]
        - [102.9925, 29.9825]
        - [102.9925, 29.9842]
        - [102.9910, 29.9842]

  # 全机队, 后续 UI 侧过滤 battery>60% 且 payload='sprayer'
  - id: available_drones
    tool: list_drones
    args: {}

  # 生成喷洒航线草稿; sensitive, 走 approval
  - id: draft_spray_mission
    tool: create_mission
    args:
      name: "植保喷洒作业"
      drone_id: "${input.drone_id}"
      waypoints:
        - [29.9830, 102.9915, 15.0]
        - [29.9840, 102.9915, 15.0]
        - [29.9840, 102.9922, 15.0]
        - [29.9830, 102.9922, 15.0]
"""

CROP_PROTECTION = Playbook(
    slug="crop-protection",
    name="植保 · 药剂喷洒前置检查",
    description=(
        "作业前天气 + 空域 + 机队 + 航线草稿一次拉齐。"
        "含 sensitive 工具 (create_mission)，触发审批。"
        "默认坐标为川农雅安试验田，请按地块改。"
    ),
    dsl_yaml=_CROP_PROTECTION_YAML,
    sample_inputs={
        "drone_id": "00000000-0000-0000-0000-000000000000",
    },
    tags=("domain", "agriculture", "sensitive"),
)


# ------------------------------------------------------------------------- #
# 5. Line inspection · 巡线 (T11.3)                                         #
# ------------------------------------------------------------------------- #

_LINE_INSPECTION_YAML = """\
# 巡线 Playbook — 输电线路日常巡检:
#   1) 检查空域 (线路走廊多为 220kV+ 电磁干扰高发)
#   2) 拉最近 24h 检测事件, 关注绝缘子/异物挂载类别
#   3) 查沿线天气 (雨/雾会影响巡检图像清晰度)
#   4) 列出已安装 CV 模型, 确认可用的异物检测模型仍在线
#
# 全只读组合, 可日常定时自动跑, 结果落 audit.
version: "0.1"
name: "line-inspection"
description: "巡线 · 输电线路日常巡检准备"
steps:
  # 一小段线路走廊的空域检查 (示例: 二滩水电站 -- 500kV 线路一段)
  - id: corridor_airspace
    tool: check_airspace
    args:
      geo:
        - [101.7833, 26.7833]
        - [101.8000, 26.7833]
        - [101.8000, 26.7900]
        - [101.7833, 26.7900]

  # 昨日 24h 沿线巡检检出, 阈值放宽到 0.4 减少漏检
  - id: yesterday_defects
    tool: list_detections
    args:
      since_minutes: 1440
      min_confidence: 0.4
      limit: 100

  - id: corridor_weather
    tool: query_weather
    args:
      lat: 26.7866
      lng: 101.7916

  # 确认 defect 检测模型仍在线
  - id: cv_models
    tool: list_installed_models
    args: {}
"""

LINE_INSPECTION = Playbook(
    slug="line-inspection",
    name="巡线 · 输电线路日常巡检准备",
    description=(
        "空域 + 昨日检出 + 天气 + CV 模型清单。"
        "100% 只读，可定时自动跑。默认坐标示例为二滩线路走廊。"
    ),
    dsl_yaml=_LINE_INSPECTION_YAML,
    sample_inputs={},
    tags=("domain", "power-grid", "readonly"),
)


# ------------------------------------------------------------------------- #
# 6. Security patrol · 安防周界巡逻 (T11.3)                                 #
# ------------------------------------------------------------------------- #

_SECURITY_PATROL_YAML = """\
# 安防 Playbook — 园区/厂区周界夜巡:
#   1) 拉最近半小时的高置信度告警 (人员翻越/车辆滞留)
#   2) 定位最近一次巡逻机的实时状态
#   3) 天气检查 (大风/暴雨 → 停飞)
#   4) 生成一次巡逻航线草稿, 走审批
#
# 场景假设: 夜间自动定时触发, 有人值守才审批派发.
version: "0.1"
name: "security-patrol"
description: "安防 · 周界夜巡响应"
steps:
  # 只看高置信度告警, 避开夜间树影/动物误检
  - id: recent_alerts
    tool: list_detections
    args:
      since_minutes: 30
      min_confidence: 0.8
      limit: 20

  - id: patrol_drone_status
    tool: get_drone_status
    args:
      drone_id: "${input.drone_id}"

  # 园区默认坐标: 请按驻地改
  - id: site_weather
    tool: query_weather
    args:
      lat: 30.6500
      lng: 104.0800

  # 巡逻航线 = 周界四个角
  - id: draft_patrol
    tool: create_mission
    args:
      name: "夜间周界巡逻"
      drone_id: "${input.drone_id}"
      waypoints:
        - [30.6495, 104.0790, 40.0]
        - [30.6495, 104.0810, 40.0]
        - [30.6505, 104.0810, 40.0]
        - [30.6505, 104.0790, 40.0]
"""

SECURITY_PATROL = Playbook(
    slug="security-patrol",
    name="安防 · 周界夜巡响应",
    description=(
        "高置信度告警 + 巡逻机状态 + 天气 + 待审批巡逻航线。"
        "含 sensitive 工具，需值守人员审批。"
    ),
    dsl_yaml=_SECURITY_PATROL_YAML,
    sample_inputs={
        "drone_id": "00000000-0000-0000-0000-000000000000",
    },
    tags=("domain", "security", "sensitive"),
)


# ------------------------------------------------------------------------- #
# Public catalog                                                            #
# ------------------------------------------------------------------------- #

PLAYBOOKS: dict[str, Playbook] = {
    p.slug: p for p in [
        # -- v2.1 E2.2 seed (T11.1) --
        MORNING_INSPECTION,
        EMERGENCY_RESPONSE,
        COMPLIANCE_PATROL,
        # -- v2.1 E2.2 domain expansion (T11.3) --
        CROP_PROTECTION,
        LINE_INSPECTION,
        SECURITY_PATROL,
    ]
}


def list_playbooks() -> list[Playbook]:
    return list(PLAYBOOKS.values())


def get_playbook(slug: str) -> Playbook | None:
    return PLAYBOOKS.get(slug)
