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
)


# ------------------------------------------------------------------------- #
# Public catalog                                                            #
# ------------------------------------------------------------------------- #

PLAYBOOKS: dict[str, Playbook] = {
    p.slug: p for p in [
        MORNING_INSPECTION,
        EMERGENCY_RESPONSE,
        COMPLIANCE_PATROL,
    ]
}


def list_playbooks() -> list[Playbook]:
    return list(PLAYBOOKS.values())


def get_playbook(slug: str) -> Playbook | None:
    return PLAYBOOKS.get(slug)
