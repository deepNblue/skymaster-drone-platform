"""GeoFence — production zone loading + built-in defaults.

Loads no-fly / restricted airspace polygons from a JSON file at startup.
Priority:

1. Explicit env var ``GEOFENCE_ZONES_FILE`` (absolute or relative path)
2. ``deploy/geofence/zones.zh_cn.json`` in the repo (packaged defaults)
3. Hard-coded builtin fallback (天安门 no-fly + 首都机场 5NM 限高)

The JSON format is a list of zone dicts:

    [
      {
        "id": "no-fly-tiananmen",
        "kind": "no_fly",
        "name": "天安门核心区禁飞",
        "polygon": [[lng, lat], ...],   // GeoJSON-style
        "max_alt_m": 0,
        "authority": "民航局 · 国务院办公厅通知(2017)"
      }
    ]

Zones can also be created at runtime via ``POST /api/v1/geofence/zones``
(admin-only) — those live in-memory only.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("skymaster.geofence.zones")


_BUILTIN: list[dict[str, Any]] = [
    {
        "id": "no-fly-tiananmen",
        "kind": "no_fly",
        "name": "天安门核心区禁飞",
        "polygon": [
            [116.390, 39.905],
            [116.404, 39.905],
            [116.404, 39.915],
            [116.390, 39.915],
        ],
        "max_alt_m": 0,
        "authority": "民航局 · 国务院办公厅通知",
    },
    {
        "id": "no-fly-pku-airport",
        "kind": "no_fly",
        "name": "首都机场净空保护(5NM)",
        # Approximate 5 NM square around the runway centroid.
        "polygon": [
            [116.500, 40.020],
            [116.680, 40.020],
            [116.680, 40.140],
            [116.500, 40.140],
        ],
        "max_alt_m": 0,
        "authority": "CCAR-93TM-R5 · 机场净空",
    },
    {
        "id": "restricted-shenzhen-cbd",
        "kind": "height",
        "name": "深圳福田 CBD 限高120m",
        "polygon": [
            [114.055, 22.535],
            [114.075, 22.535],
            [114.075, 22.555],
            [114.055, 22.555],
        ],
        "max_alt_m": 120,
        "authority": "深圳市公安局无人机管理办法",
    },
]


def load_zones() -> list[dict[str, Any]]:
    """Return the list of zone dicts to seed the GeoFence engine with."""
    env_path = os.getenv("GEOFENCE_ZONES_FILE")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    # Repo default alongside deploy/ (works both in dev and packaged runs)
    here = Path(__file__).resolve()
    # here = <repo>/backend-v0.1/app/services/geofence_zones.py
    #        parents: 0=services, 1=app, 2=backend-v0.1, 3=<repo>
    candidates.append(
        here.parents[3] / "deploy" / "geofence" / "zones.zh_cn.json"
    )
    # Also try repo-local relative path for CI where cwd = backend-v0.1
    candidates.append(Path("../deploy/geofence/zones.zh_cn.json"))
    candidates.append(Path("deploy/geofence/zones.zh_cn.json"))

    for c in candidates:
        try:
            if c.is_file():
                with c.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    log.info("Loaded %d geofence zones from %s", len(data), c)
                    return data
        except Exception:  # noqa: BLE001
            log.exception("Failed to load geofence file %s — trying next", c)

    log.warning(
        "No geofence zones file found; falling back to %d built-in zones",
        len(_BUILTIN),
    )
    return list(_BUILTIN)
