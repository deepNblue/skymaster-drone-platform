"""Geo-Fence Engine — v2.0 compliance track.

Static in-memory registry of no-fly / height-limit polygons. Used by
mission_dispatcher and the live UI to check waypoints before takeoff.

For v0.1 we seed a small set of well-known Chinese sensitive zones so
the compliance flow can be demoed without extra config. In production
these polygons come from AMS/民航局/EASA feeds via cron sync.

Zone types:
    - ``no_fly``  : hard block (禁飞区)
    - ``restricted``: warn + require special approval (限飞区)
    - ``height`` : altitude cap in metres (限高区)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- built-in seed
_SEED_ZONES: list[dict] = [
    {
        "id": "bj-tiananmen",
        "name": "北京天安门核心禁飞区",
        "kind": "no_fly",
        "polygon": [
            [116.386, 39.900], [116.410, 39.900],
            [116.410, 39.918], [116.386, 39.918],
        ],
        "source": "seed",
    },
    {
        "id": "bj-capital-airport",
        "name": "北京首都国际机场净空保护区",
        "kind": "no_fly",
        "polygon": [
            [116.55, 40.03], [116.68, 40.03],
            [116.68, 40.11], [116.55, 40.11],
        ],
        "source": "seed",
    },
    {
        "id": "cd-shuangliu-airport",
        "name": "成都双流国际机场净空保护区",
        "kind": "no_fly",
        "polygon": [
            [103.90, 30.55], [104.02, 30.55],
            [104.02, 30.62], [103.90, 30.62],
        ],
        "source": "seed",
    },
    {
        "id": "bj-height-120",
        "name": "北京城区默认限高 120m",
        "kind": "height",
        "polygon": [
            [116.20, 39.80], [116.55, 39.80],
            [116.55, 40.02], [116.20, 40.02],
        ],
        "max_alt_m": 120.0,
        "source": "seed",
    },
]


@dataclass
class Zone:
    id: str
    name: str
    kind: str  # 'no_fly' | 'restricted' | 'height'
    polygon: list[list[float]]  # [[lng, lat], ...]
    max_alt_m: Optional[float] = None
    source: str = "seed"

    def contains(self, lng: float, lat: float) -> bool:
        return _point_in_poly(lng, lat, self.polygon)


@dataclass
class Violation:
    zone_id: str
    zone_name: str
    kind: str
    detail: str
    waypoint_idx: Optional[int] = None


@dataclass
class CheckResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": [v.__dict__ for v in self.violations],
        }


class GeoFenceEngine:
    """Read-only zone registry with waypoint check API."""

    def __init__(self) -> None:
        self._zones: dict[str, Zone] = {}
        self._load_seed()

    def _load_seed(self) -> None:
        """Seed zones from geofence_zones.load_zones() + optional overlay."""
        from app.services.geofence_zones import load_zones
        # Field whitelist — extra fields (e.g. 'authority') from zones.json
        # are stripped so the dataclass constructor accepts them.
        _ALLOWED = {"id", "kind", "name", "polygon", "max_alt_m"}
        for z in load_zones():
            try:
                clean = {k: v for k, v in z.items() if k in _ALLOWED}
                # Keep original 'kind' — GeoFence only supports no_fly/height.
                # Map 'restricted' → 'height' for compat if max_alt_m provided.
                if clean.get("kind") == "restricted" and clean.get("max_alt_m"):
                    clean["kind"] = "height"
                self._zones[z["id"]] = Zone(**clean)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                logger.exception("Bad zone spec skipped: %s", z.get("id"))
        # Extra env overlay (kept for backward compat): loads on top of base.
        path = os.getenv("GEOFENCE_EXTRA_ZONES_FILE")
        if path and Path(path).exists():
            try:
                extra = json.loads(Path(path).read_text())
                for z in extra:
                    clean = {k: v for k, v in z.items() if k in _ALLOWED}
                    self._zones[z["id"]] = Zone(**clean)
                logger.info("GeoFence loaded %d extra zones from %s", len(extra), path)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to load %s", path)

    def all_zones(self) -> list[Zone]:
        return list(self._zones.values())

    def check_waypoints(
        self,
        waypoints: list[dict],
    ) -> CheckResult:
        """waypoints: list of {'lat', 'lng', 'alt'}."""
        violations: list[Violation] = []
        for i, wp in enumerate(waypoints):
            lat = float(wp.get("lat", 0))
            lng = float(wp.get("lng", 0))
            alt = float(wp.get("alt", 0))
            for z in self._zones.values():
                if not z.contains(lng, lat):
                    continue
                if z.kind == "no_fly":
                    violations.append(Violation(
                        zone_id=z.id, zone_name=z.name, kind="no_fly",
                        detail=f"waypoint {i} 落入禁飞区 {z.name}",
                        waypoint_idx=i,
                    ))
                elif z.kind == "restricted":
                    violations.append(Violation(
                        zone_id=z.id, zone_name=z.name, kind="restricted",
                        detail=f"waypoint {i} 进入限飞区 {z.name}",
                        waypoint_idx=i,
                    ))
                elif z.kind == "height" and z.max_alt_m is not None:
                    if alt > z.max_alt_m:
                        violations.append(Violation(
                            zone_id=z.id, zone_name=z.name, kind="height",
                            detail=(
                                f"waypoint {i} 高度 {alt:.0f}m 超过 "
                                f"{z.name} 限高 {z.max_alt_m:.0f}m"
                            ),
                            waypoint_idx=i,
                        ))
        return CheckResult(ok=(not violations), violations=violations)


def _point_in_poly(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


_engine: Optional[GeoFenceEngine] = None


def get_geofence() -> GeoFenceEngine:
    global _engine
    if _engine is None:
        _engine = GeoFenceEngine()
    return _engine
