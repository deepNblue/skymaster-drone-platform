"""Aggregation service for the Nanning 12309 drone-defense scenario view.

Reuses existing data sources instead of reimplementing their business logic.
Every scope/threshold/label comes from ``backend/config/scenarios/12309.json``.
Each block degrades independently: a broken MediaMTX or a missing DJI
connector never takes down the whole overview.
"""
from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drone import Drone
from app.models.flight_approval import FlightApproval
from app.models.scene import Scene
from app.models.vision_copilot import VisionDetection
from app.models.user import User

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = _BACKEND_ROOT / "config" / "scenarios" / "12309.json"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _as_dict(value: Any) -> Dict[str, Any]:
    """SQLite stores JSONB as TEXT; normalize both backends to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _in_bbox(lat: Any, lng: Any, bbox: List[float]) -> bool:
    if lat is None or lng is None:
        return True  # no coordinates: keep rather than silently drop
    try:
        west, south, east, north = [float(v) for v in bbox]
        return south <= float(lat) <= north and west <= float(lng) <= east
    except (TypeError, ValueError):
        return True


def _polygon_touches_bbox(polygon: Any, bbox: List[float]) -> bool:
    """True when any polygon vertex falls inside the scenario bbox.

    Approvals without a usable polygon are kept: hiding an approval because
    of missing metadata is worse than showing one extra item.
    """
    if not isinstance(polygon, list) or not polygon:
        return True
    try:
        west, south, east, north = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return True
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            lng, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        if south <= lat <= north and west <= lng <= east:
            return True
    return False


def _failed(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason[:300], "items": [], "count": 0}


class Scenario12309Service:
    def __init__(
        self,
        connector: Any = None,
        stream_manager: Any = None,
        config_path: Optional[str] = None,
    ) -> None:
        path = config_path or os.getenv("SCENARIO_12309_CONFIG") or str(DEFAULT_CONFIG)
        self.config = _read_json(Path(path))
        self.connector = connector
        self._stream_manager = stream_manager

    # ------------------------------------------------------------------ meta
    @property
    def scope(self) -> Dict[str, Any]:
        return self.config.get("scope") or {}

    @property
    def windows(self) -> Dict[str, Any]:
        return self.config.get("windows") or {}

    def meta(self) -> Dict[str, Any]:
        return {
            "id": self.config.get("id", "12309"),
            "name": self.config.get("name", "12309 场景"),
            "short_name": self.config.get("short_name", "12309"),
            "description": self.config.get("description", ""),
            "region": self.config.get("region") or {},
            "owner": self.config.get("owner", ""),
            "kpis": self.config.get("kpis") or [],
            "config_loaded": bool(self.config),
        }

    def severity(self, confidence: Any) -> Dict[str, str]:
        try:
            score = float(confidence or 0)
        except (TypeError, ValueError):
            score = 0.0
        for rule in self.config.get("severity_rules") or []:
            try:
                if score >= float(rule.get("min_confidence", 0)):
                    return {"level": str(rule.get("level", "low")),
                            "label": str(rule.get("label", "一般"))}
            except (TypeError, ValueError):
                continue
        return {"level": "low", "label": "一般"}

    # ---------------------------------------------------------------- blocks
    async def _fleet(self, db: AsyncSession, user: User) -> Dict[str, Any]:
        stmt = select(Drone)
        if getattr(user, "org_id", None):
            stmt = stmt.where(Drone.org_id == user.org_id)
        rows = (await db.execute(stmt.limit(200))).scalars().all()
        label_key = str(self.scope.get("drone_label_contains") or "").lower()
        allowed_sns = {str(s) for s in self.scope.get("drone_sns") or []}
        items = []
        for row in rows:
            meta = _as_dict(row.meta)
            label = str(meta.get("label") or "")
            sn = str(row.sn or "")
            hit = sn in allowed_sns or (bool(label_key) and label_key in label.lower())
            if not hit:
                continue
            items.append({
                "id": str(row.id),
                "sn": sn,
                "label": label,
                "model": row.model,
                "protocol": row.protocol,
                "status": row.status,
                "dji_device_sn": meta.get("dji_device_sn"),
                "dji_gateway_sn": meta.get("dji_gateway_sn"),
                "source": "db",
            })
        return {"available": True, "items": items, "count": len(items)}

    def _routes(self) -> Dict[str, Any]:
        routes = []
        if self.connector is not None and hasattr(self.connector, "mission_routes"):
            try:
                routes = self.connector.mission_routes() or []
            except Exception:  # noqa: BLE001
                routes = []
        if not routes:
            routes = _read_json(
                _BACKEND_ROOT / "config" / "dji_mission_routes.json").get("routes") or []
        prefix = str(self.scope.get("route_id_prefix") or "")
        items = [
            r for r in routes
            if isinstance(r, dict) and (not prefix or str(r.get("id", "")).startswith(prefix))
        ]
        return {"available": True, "items": items, "count": len(items)}

    def _missions(self, fleet_sns: List[str]) -> Dict[str, Any]:
        if self.connector is None:
            return _failed("DJI 连接器未挂载（需 START_TELEMETRY_STACK=true 且已绑定 DJI 飞机）")
        try:
            raw = self.connector.mission_status() or {}
            missions = raw.get("missions") or []
        except Exception as exc:  # noqa: BLE001
            return _failed(f"读取任务状态失败：{exc}")
        allowed = set(fleet_sns)
        items = []
        for m in missions:
            if not isinstance(m, dict):
                continue
            sn = str(m.get("drone_sn") or "")
            if allowed and sn and sn not in allowed:
                continue
            items.append({
                "task_id": m.get("task_id"),
                "flight_id": m.get("flight_id"),
                "drone_sn": sn,
                "state": m.get("state"),
                "progress": m.get("progress"),
                "idx": m.get("idx"),
                "waypoint_count": len(m.get("waypoints") or []),
                "breakpoint": m.get("breakpoint"),
                "updated_at": _iso(m.get("updated_at")),
                "kmz_filename": (m.get("kmz") or {}).get("filename"),
            })
        return {"available": True, "items": items, "count": len(items)}

    async def _alerts(self, db: AsyncSession, user: User) -> Dict[str, Any]:
        minutes = int(self.windows.get("alerts_minutes") or 1440)
        limit = int(self.windows.get("list_limit") or 20)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        stmt = select(VisionDetection).where(VisionDetection.created_at >= cutoff)
        if getattr(user, "org_id", None):
            stmt = stmt.where(VisionDetection.tenant_id == user.org_id)
        stmt = stmt.order_by(VisionDetection.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        bbox = list((self.config.get("region") or {}).get("bbox") or [])
        open_statuses = set(self.config.get("alert_open_statuses") or [])
        items = []
        for row in rows:
            if bbox and not _in_bbox(row.lat, row.lng, bbox):
                continue
            sev = self.severity(row.confidence)
            items.append({
                "id": str(row.id),
                "label": row.label,
                "confidence": row.confidence,
                "severity": sev["level"],
                "severity_label": sev["label"],
                "status": row.status,
                "open": row.status in open_statuses,
                "lat": row.lat,
                "lng": row.lng,
                "drone_id": str(row.drone_id) if row.drone_id else None,
                "mission_id": str(row.mission_id) if row.mission_id else None,
                "created_at": _iso(row.created_at),
            })
        return {"available": True, "items": items, "count": len(items),
                "window_minutes": minutes}

    async def _approvals(self, db: AsyncSession, user: User) -> Dict[str, Any]:
        limit = int(self.windows.get("list_limit") or 20)
        stmt = select(FlightApproval)
        if getattr(user, "org_id", None):
            stmt = stmt.where(FlightApproval.tenant_id == user.org_id)
        stmt = stmt.order_by(FlightApproval.created_at.desc()).limit(limit * 2)
        rows = (await db.execute(stmt)).scalars().all()
        bbox = list((self.config.get("region") or {}).get("bbox") or [])
        status_map = self.config.get("approval_status_map") or {}
        open_statuses = set(self.config.get("approval_open_statuses") or [])
        items = []
        for row in rows:
            if bbox and not _polygon_touches_bbox(row.area_polygon, bbox):
                continue
            items.append({
                "id": str(row.id),
                "title": row.title,
                "category": row.category,
                "status": row.status,
                "status_label": status_map.get(row.status, row.status),
                "open": row.status in open_statuses,
                "max_alt_m": row.max_alt_m,
                "start_ts": _iso(row.start_ts),
                "end_ts": _iso(row.end_ts),
                "created_at": _iso(row.created_at),
            })
            if len(items) >= limit:
                break
        return {"available": True, "items": items, "count": len(items)}

    async def _evidence(self, db: AsyncSession, user: User) -> Dict[str, Any]:
        limit = int(self.windows.get("list_limit") or 20)
        stmt = select(Scene)
        if getattr(user, "org_id", None):
            stmt = stmt.where(Scene.org_id == user.org_id)
        else:
            stmt = stmt.where(Scene.owner_user_id == user.id)
        stmt = stmt.order_by(Scene.created_at.desc()).limit(limit * 2)
        rows = (await db.execute(stmt)).scalars().all()
        keywords = [str(k).lower() for k in self.scope.get("evidence_name_contains") or []]
        items = []
        for row in rows:
            name = str(row.name or "")
            if keywords and not any(k in name.lower() for k in keywords):
                continue
            items.append({
                "id": str(row.id),
                "name": name,
                "status": row.status,
                "scene_kind": row.scene_kind,
                "n_source_images": row.n_source_images,
                "n_gaussians": row.n_gaussians,
                "psnr_train": row.psnr_train,
                "asset_count": len(row.assets or []),
                "created_at": _iso(row.created_at),
            })
            if len(items) >= limit:
                break
        return {"available": True, "items": items, "count": len(items)}

    async def _streams(self) -> Dict[str, Any]:
        try:
            if self._stream_manager is None:
                from app.services.stream_manager import get_stream_manager
                manager = get_stream_manager()
            else:
                manager = self._stream_manager
            data = await manager.list_active_streams()
        except Exception as exc:  # noqa: BLE001
            return _failed(f"视频流服务不可用：{exc}")
        raw = data.get("items") if isinstance(data, dict) else data
        items = []
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            items.append({
                "drone_id": entry.get("drone_id") or entry.get("name"),
                "name": entry.get("name"),
                "active": bool(entry.get("active", True)),
                "hls_url": entry.get("hls_url"),
                "rtsp_url": entry.get("rtsp_url"),
            })
        return {"available": True, "items": items, "count": len(items)}

    # ------------------------------------------------------------- aggregate
    @staticmethod
    async def _safe(name: str, fn: Callable) -> tuple:
        """Allow sync or async block readers; never let one block fail the page."""
        try:
            value = fn()
            if inspect.isawaitable(value):
                value = await value
            return name, value
        except Exception as exc:  # noqa: BLE001
            return name, _failed(f"{name} 读取失败：{exc}")

    async def overview(self, db: AsyncSession, user: User) -> Dict[str, Any]:
        """Build the full scenario overview; each block degrades independently."""
        results: Dict[str, Any] = {"meta": self.meta(), "routes": self._routes()}
        key, block = await self._safe("fleet", lambda: self._fleet(db, user))
        results[key] = block
        fleet_sns = [
            str(i.get("dji_device_sn") or i.get("sn") or "")
            for i in results["fleet"].get("items", [])
        ]

        calls = [
            ("missions", lambda: self._missions(fleet_sns)),
            ("alerts", lambda: self._alerts(db, user)),
            ("approvals", lambda: self._approvals(db, user)),
            ("evidence", lambda: self._evidence(db, user)),
            ("streams", self._streams),
        ]
        for name, fn in calls:
            key, block = await self._safe(name, fn)
            results[key] = block

        results["kpi"] = self._kpi(results)
        results["timeline"] = self._timeline(results)
        results["generated_at"] = datetime.now(timezone.utc).isoformat()
        return results

    def _kpi(self, results: Dict[str, Any]) -> Dict[str, Any]:
        alerts = results["alerts"].get("items") or []
        approvals = results["approvals"].get("items") or []
        return {
            "fleet_online": sum(
                1 for i in results["fleet"].get("items", [])
                if str(i.get("status", "")).lower() in {"online", "active", "flying"}
            ),
            "active_missions": sum(
                1 for i in results["missions"].get("items", [])
                if i.get("state") in {"running", "paused"}
            ),
            "open_alerts": sum(1 for i in alerts if i.get("open")),
            "pending_approvals": sum(1 for i in approvals if i.get("open")),
            "live_streams": results["streams"].get("count", 0),
            "evidence_count": results["evidence"].get("count", 0),
        }

    def _timeline(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        limit = int(self.windows.get("timeline_limit") or 12)
        events: List[Dict[str, Any]] = []
        for kind, block_key, ts_key, title_key in (
            ("alert", "alerts", "created_at", "label"),
            ("approval", "approvals", "created_at", "title"),
            ("mission", "missions", "updated_at", "task_id"),
            ("evidence", "evidence", "created_at", "name"),
        ):
            for item in results.get(block_key, {}).get("items") or []:
                events.append({
                    "kind": kind,
                    "at": item.get(ts_key),
                    "title": item.get(title_key),
                    "status": item.get("status"),
                    "id": item.get("id") or item.get("task_id"),
                })
        events = [e for e in events if e.get("at")]
        events.sort(key=lambda e: str(e["at"]), reverse=True)
        return events[:limit]
