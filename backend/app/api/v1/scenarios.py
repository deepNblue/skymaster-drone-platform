"""Scenario-level aggregation endpoints.

Currently hosts the Nanning 12309 defense view. The scenario definitions live
in ``backend/config/scenarios/*.json`` and are never hardcoded here.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from app.deps import get_current_user, get_db
from app.models.user import User
from app.services.scenario_12309 import Scenario12309Service, _BACKEND_ROOT, _read_json

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
async def list_scenarios(
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Available scenario definitions loaded from the config directory."""
    folder = _BACKEND_ROOT / "config" / "scenarios"
    items = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            cfg = _read_json(path)
            if not cfg:
                continue
            items.append({
                "id": cfg.get("id", path.stem),
                "name": cfg.get("name", path.stem),
                "short_name": cfg.get("short_name", path.stem),
            })
    return {"items": items, "count": len(items)}


@router.get("/12309/overview")
async def scenario_12309_overview(
    request: Request,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
) -> Dict[str, Any]:
    """Aggregated 12309 defense posture; each data block degrades independently."""
    service = Scenario12309Service(
        connector=getattr(request.app.state, "dji_connector", None),
    )
    return await service.overview(db, user)
