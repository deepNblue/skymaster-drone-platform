"""Authority routing rules — decide which departments a flight must notify.

Rules per PRODUCT_SPEC §3.14.1 authority matrix. Highly conservative: err
on the side of MORE authorities so the pilot never misses a report.

Static rule table drives the routing decision from three inputs:

    1. bbox / polygon of the flight area (lng, lat)
    2. altitude ceiling
    3. purpose (航拍/巡检/农业/表演/警务/应急...)

Also honors ``category`` (routine/special/emergency) — emergency skips
optional authorities and only keeps P0/P1 mandatory ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# --- Authority catalog -----------------------------------------------------


@dataclass(frozen=True)
class Authority:
    code: str
    name: str
    channel: str      # api | rpa | manual
    priority: int     # 0 = P0 mandatory, 1 = P1 mandatory, 2 = P2 optional
    scope: str        # national | provincial | city | category-specific


AUTHORITIES: dict[str, Authority] = {
    "uom": Authority(
        code="uom",
        name="中国民航局 UOM 一体化监管平台",
        channel="api",
        priority=0,
        scope="national",
    ),
    "local_police": Authority(
        code="local_police",
        name="属地公安（治安/科技）",
        channel="rpa",
        priority=0,
        scope="city",
    ),
    "atc": Authority(
        code="atc",
        name="军民航空管委（管制/临时空域）",
        channel="manual",
        priority=1,
        scope="provincial",
    ),
    "market_regulator": Authority(
        code="market_regulator",
        name="市场监督管理局（≥15kg 登记）",
        channel="manual",
        priority=1,
        scope="national",
    ),
    "forestry": Authority(
        code="forestry",
        name="国家林草局 / 自然保护区",
        channel="manual",
        priority=2,
        scope="category-specific",
    ),
    "tourism": Authority(
        code="tourism",
        name="地方文旅/城管（景区/公园）",
        channel="rpa",
        priority=2,
        scope="city",
    ),
    "maritime": Authority(
        code="maritime",
        name="海事局（海上/港口）",
        channel="manual",
        priority=2,
        scope="city",
    ),
}


# --- Geofence helpers ------------------------------------------------------


def _polygon_bbox(polygon: Optional[list]) -> Optional[tuple[float, float, float, float]]:
    """(min_lng, min_lat, max_lng, max_lat) — None if empty/invalid."""
    if not polygon:
        return None
    try:
        lngs = [p[0] for p in polygon]
        lats = [p[1] for p in polygon]
        return (min(lngs), min(lats), max(lngs), max(lats))
    except Exception:  # noqa: BLE001
        return None


def _bbox_overlaps(a: tuple, b: tuple) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


# Coarse regional/scenario keywords → additional authorities.
# In production these come from an authoritative GIS layer.
# 南宁市 approximate bbox: (108.15, 22.55, 108.50, 22.95)
_CITY_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "nanning": (108.15, 22.55, 108.50, 22.95),
    "beijing": (116.20, 39.75, 116.65, 40.10),
    "shanghai": (121.30, 31.00, 121.75, 31.45),
}

_NATURE_RESERVE_BBOXES: list[tuple[float, float, float, float]] = [
    # 大明山自然保护区（南宁武鸣区，示意）
    (108.32, 23.30, 108.55, 23.55),
]

_COAST_BBOXES: list[tuple[float, float, float, float]] = [
    # 北海涠洲岛 / 沿海一带（示意）
    (109.05, 21.00, 109.40, 21.65),
]


# --- Rule engine -----------------------------------------------------------


def is_high_risk(
    *,
    polygon: list[list[float]] | None,
    max_alt_m: float | None,
    category: str | None,
) -> tuple[bool, str | None]:
    """T7.0 second-approval trigger.

    Returns (True, reason) if the flight requires a supervisor sign-off
    before the fan-out; (False, None) otherwise.

    Triggers (any one):
      * category == 'emergency'
      * category == 'special'
      * max_alt_m > 120  (Class-A boundary, GB/T 42590-2023)
      * polygon area > 1 km²  (rough shoelace on lon/lat degrees;
                              1 km² ~ 8.1e-5 sq-degree at 中纬度)
    """
    if category == "emergency":
        return True, "emergency category"
    if category == "special":
        return True, "special category"
    if max_alt_m is not None and max_alt_m > 120:
        return True, f"max_alt_m={max_alt_m:g} > 120m"
    if polygon and len(polygon) >= 3:
        # shoelace in degree units (rough, but stable for the trigger).
        n = len(polygon)
        s = 0.0
        for i in range(n):
            x1, y1 = polygon[i][0], polygon[i][1]
            x2, y2 = polygon[(i + 1) % n][0], polygon[(i + 1) % n][1]
            s += x1 * y2 - x2 * y1
        area_deg2 = abs(s) * 0.5
        # 1 deg lat ≈ 111 km; 1 deg lon ≈ 111 * cos(lat) km.
        # Use lat ~ centroid.
        lat_mean = sum(p[1] for p in polygon) / n
        import math
        km2 = area_deg2 * 111.0 * 111.0 * math.cos(math.radians(lat_mean))
        if km2 > 1.0:
            return True, f"area ~ {km2:.2f} km² > 1 km²"
    return False, None


def route_authorities(
    *,
    polygon: Optional[list] = None,
    max_alt_m: Optional[float] = None,
    purpose: Optional[str] = None,
    aircraft_weight_kg: Optional[float] = None,
    category: str = "routine",
) -> list[dict]:
    """Return the ordered list of authorities that must be notified.

    Each item::

        {"code", "name", "channel", "priority", "reason"}

    Rules (union):
      - **UOM** is ALWAYS required (national mandate).
      - **local_police** if flight lies over a city bbox we know.
      - **atc** if altitude > 120m OR category != routine.
      - **market_regulator** if aircraft_weight_kg >= 15.
      - **forestry** if polygon overlaps a known reserve.
      - **tourism** if purpose contains 景区/公园/表演/文旅.
      - **maritime** if polygon overlaps a known coast/port bbox.

    ``category == "emergency"`` drops priority-2 authorities.
    """
    out: list[dict] = []
    bbox = _polygon_bbox(polygon)
    p = (purpose or "").lower()

    def _add(code: str, reason: str) -> None:
        a = AUTHORITIES.get(code)
        if not a:
            return
        if category == "emergency" and a.priority >= 2:
            return
        if any(o["code"] == code for o in out):
            return
        out.append({
            "code": a.code,
            "name": a.name,
            "channel": a.channel,
            "priority": a.priority,
            "reason": reason,
        })

    # Always required.
    _add("uom", "民航局 UOM 全国强制")

    # Altitude gate.
    if max_alt_m is not None and max_alt_m > 120:
        _add("atc", f"最大高度 {max_alt_m:.0f} m > 120 m，需空管协调")
    if category != "routine":
        _add("atc", f"作业类别 {category}，需空管审批")

    # Weight gate.
    if aircraft_weight_kg is not None and aircraft_weight_kg >= 15:
        _add("market_regulator", f"整机 {aircraft_weight_kg} kg ≥ 15 kg，市监登记")

    # Geo gates.
    if bbox is not None:
        for city, bb in _CITY_BBOXES.items():
            if _bbox_overlaps(bbox, bb):
                _add("local_police", f"属地公安（{city}）")
                break
        for bb in _NATURE_RESERVE_BBOXES:
            if _bbox_overlaps(bbox, bb):
                _add("forestry", "自然保护区")
                break
        for bb in _COAST_BBOXES:
            if _bbox_overlaps(bbox, bb):
                _add("maritime", "海上/港口临近")
                break

    # Purpose gates.
    if any(k in p for k in ("景区", "公园", "文旅", "表演", "灯光")):
        _add("tourism", "景区/文旅/表演作业")

    # Deterministic order: priority asc, code asc.
    out.sort(key=lambda x: (x["priority"], x["code"]))
    return out
