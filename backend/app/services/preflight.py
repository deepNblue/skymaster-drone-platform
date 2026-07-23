"""Pre-flight checklist — PRODUCT_SPEC §3.14.2 智能预检.

Runs a comprehensive check RIGHT BEFORE takeoff:

    ✔ 有对应的 approved FlightApproval
    ✔ 时间窗内（未过期、未未生效）
    ✔ 飞手执照非空
    ✔ 保险单号非空
    ✔ 飞行区域未越出 approved polygon（预留 geofence 校验）
    ✔ 最大高度 ≤ approved max_alt_m
    ✔ Remote ID broadcast 开关已开（预留）

Returns a structured result so the frontend can render each rule and its
outcome (pass / warn / fail). Any ``fail`` blocks takeoff.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CheckItem:
    key: str
    name: str
    severity: str   # pass | warn | fail
    detail: str


def _fail(key: str, name: str, detail: str) -> CheckItem:
    return CheckItem(key=key, name=name, severity="fail", detail=detail)


def _warn(key: str, name: str, detail: str) -> CheckItem:
    return CheckItem(key=key, name=name, severity="warn", detail=detail)


def _pass(key: str, name: str, detail: str = "OK") -> CheckItem:
    return CheckItem(key=key, name=name, severity="pass", detail=detail)


def preflight_check(
    approval: object,
    *,
    at_ts: Optional[datetime] = None,
    remote_id_broadcast: Optional[bool] = None,
    intended_max_alt_m: Optional[float] = None,
) -> dict:
    """Run all checks and return `{ok, blocking, items[]}`."""
    now = at_ts or datetime.now(tz=timezone.utc)
    items: list[CheckItem] = []

    if approval is None:
        items.append(_fail("approval_exists", "报备存在性", "找不到对应 FlightApproval 记录"))
        return _finalize(items)

    status = getattr(approval, "status", None)
    if status != "approved":
        items.append(_fail("approval_status", "报备状态", f"当前状态 {status!r}，仅 approved 允许起飞"))
    else:
        items.append(_pass("approval_status", "报备状态", "approved"))

    # Time window.
    start = getattr(approval, "start_ts", None)
    end = getattr(approval, "end_ts", None)
    # Normalize naive → UTC for comparison.
    def _aware(d):
        if d is None: return None
        if d.tzinfo is None: return d.replace(tzinfo=timezone.utc)
        return d
    start = _aware(start)
    end = _aware(end)
    if start and end:
        if now < start:
            items.append(_fail("time_window", "时间窗", f"未到起飞时间（{start.isoformat()}）"))
        elif now > end:
            items.append(_fail("time_window", "时间窗", f"已过报备时间（{end.isoformat()}）"))
        else:
            items.append(_pass("time_window", "时间窗", f"{start.isoformat()} ~ {end.isoformat()}"))
    else:
        items.append(_warn("time_window", "时间窗", "报备缺少 start_ts/end_ts"))

    # Pilot license.
    lic = getattr(approval, "pilot_license", None)
    if lic:
        items.append(_pass("pilot_license", "飞手执照", lic))
    else:
        items.append(_fail("pilot_license", "飞手执照", "报备未填写飞手执照号"))

    # Aircraft registration.
    reg = getattr(approval, "aircraft_reg", None)
    if reg:
        items.append(_pass("aircraft_reg", "无人机注册号", reg))
    else:
        items.append(_fail("aircraft_reg", "无人机注册号", "民航局 UAS 注册号缺失"))

    # Insurance.
    ins = getattr(approval, "insurance_no", None)
    if ins:
        items.append(_pass("insurance", "第三方责任险", ins))
    else:
        items.append(_warn("insurance", "第三方责任险", "未填写保单号"))

    # Altitude.
    max_alt = getattr(approval, "max_alt_m", None)
    if intended_max_alt_m is not None and max_alt is not None:
        if intended_max_alt_m > max_alt:
            items.append(_fail(
                "altitude",
                "计划高度",
                f"计划 {intended_max_alt_m:.0f} m 超过报备 {max_alt:.0f} m",
            ))
        else:
            items.append(_pass("altitude", "计划高度", f"{intended_max_alt_m:.0f} m ≤ {max_alt:.0f} m"))
    elif max_alt is not None:
        items.append(_pass("altitude", "报备最大高度", f"{max_alt:.0f} m"))

    # Remote ID.
    if remote_id_broadcast is True:
        items.append(_pass("remote_id", "Remote ID 广播", "已开启"))
    elif remote_id_broadcast is False:
        items.append(_fail("remote_id", "Remote ID 广播", "未开启，违反《无人机实时位置广播规定》"))
    else:
        items.append(_warn("remote_id", "Remote ID 广播", "状态未上报，起飞前必须确认开启"))

    # Authority rollup.
    authorities = getattr(approval, "authorities", None) or []
    if authorities:
        pending = [a for a in authorities if a.status not in ("approved", "skipped")]
        if pending:
            items.append(_fail(
                "authorities",
                "各主管审批",
                f"{len(pending)} 个主管未通过：" + ", ".join(a.authority_code for a in pending),
            ))
        else:
            items.append(_pass("authorities", "各主管审批", f"{len(authorities)} 个主管全部就绪"))

    return _finalize(items)


def _finalize(items: list[CheckItem]) -> dict:
    fails = [i for i in items if i.severity == "fail"]
    warns = [i for i in items if i.severity == "warn"]
    return {
        "ok": len(fails) == 0,
        "blocking": len(fails) > 0,
        "fail_count": len(fails),
        "warn_count": len(warns),
        "items": [i.__dict__ for i in items],
    }
