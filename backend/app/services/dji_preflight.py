"""Data-driven preflight checklist for DJI real-device integration.

The checklist lives in ``backend/config/dji_preflight.json``. Each item says
where to read the current value (``source`` / ``key``), how to judge it
(``check``) and which field must be confirmed on the real device (``verify``).
No firmware-specific value is hardcoded here, and no secret is ever exposed:
secret values are rendered as 已配置 / 未配置.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.dji_cloud_connector import (
    DEFAULT_CALIBRATION_CONFIG,
    DEFAULT_CONTROL_CONFIG,
    DEFAULT_MISSION_CONFIG,
    DEFAULT_MISSION_ROUTES,
    DEFAULT_TLS_CONFIG,
    DEFAULT_WPML_CONFIG,
    _BACKEND_ROOT as BACKEND_ROOT,
)

DEFAULT_PREFLIGHT_CONFIG = BACKEND_ROOT / "config" / "dji_preflight.json"

_CONFIG_FILES = {
    "calibration": DEFAULT_CALIBRATION_CONFIG,
    "control": DEFAULT_CONTROL_CONFIG,
    "mission": DEFAULT_MISSION_CONFIG,
    "routes": DEFAULT_MISSION_ROUTES,
    "tls": DEFAULT_TLS_CONFIG,
    "wpml": DEFAULT_WPML_CONFIG,
}

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", ""}
_SECRET_FIELDS = {"username", "password", "password_confirm", "secret", "token"}


def _dig(data: Any, dotted: str) -> Any:
    """Read a dotted path from nested dicts/lists; return None when absent."""
    if not dotted:
        return data
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            return None
    return cur


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class DJIPreflight:
    """Build a structured, non-sensitive real-device readiness report."""

    def __init__(
        self,
        connector: Any = None,
        settings: Any = None,
        config_path: Optional[str] = None,
    ) -> None:
        self.connector = connector
        self.settings = settings
        config_path = config_path or os.getenv("DJI_PREFLIGHT_CONFIG") or None
        self.config_path = Path(config_path) if config_path else DEFAULT_PREFLIGHT_CONFIG
        self.checklist = _read_json(self.config_path)
        self._configs = self._collect_configs()
        self._runtime = self._runtime_snapshot()

    # ------------------------------------------------------------ snapshots
    def _collect_configs(self) -> Dict[str, Any]:
        configs: Dict[str, Any] = {}
        for name, default in _CONFIG_FILES.items():
            configs[name] = _read_json(default)
        c = self.connector
        if c is None:
            return configs
        attrs = {
            "calibration": "calibration_config",
            "control": "control_config",
            "mission": "mission_config",
            "tls": "tls_config",
            "wpml": "wpml_config",
        }
        for name, attr in attrs.items():
            value = getattr(c, attr, None)
            if isinstance(value, dict):
                configs[name] = value
        routes = getattr(c, "_mission_routes", None)
        if isinstance(routes, list):
            configs["routes"] = {"routes": routes}
        return configs

    def _runtime_snapshot(self) -> Dict[str, Any]:
        c = self.connector
        s = self.settings
        def setting(name: str, default: Any) -> Any:
            value = getattr(s, name, None) if s is not None else None
            return default if value is None else value

        broker_host = getattr(c, "broker_host", None) if c else None
        broker_port = getattr(c, "broker_port", None) if c else None
        mode = getattr(c, "mode", None) if c else None
        gateway = getattr(c, "gateway_sn", None) if c else None
        client_id = getattr(c, "client_id", None) if c else None
        username = getattr(c, "username", None) if c else None
        password = getattr(c, "password", None) if c else None

        aircraft: List[str] = list(getattr(c, "drone_id_map", {}).keys()) if c else []
        if c is not None and not aircraft:
            aircraft = [
                d.get("sn", "") for d in
                (getattr(c, "topology", {}) or {}).get("sub_devices", [])
                if isinstance(d, dict)
            ]

        try:
            paho_installed = importlib.util.find_spec("paho.mqtt.client") is not None
        except (ImportError, ValueError):
            paho_installed = False

        return {
            "mode": mode or str(setting("dji_mode", "mock")),
            "gateway_sn": gateway or str(setting("dji_gateway_sn", "MOCKDOCK001")),
            "broker_host": broker_host or str(setting("dji_broker_host", "127.0.0.1")),
            "broker_port": broker_port or setting("dji_broker_port", 1883),
            "client_id": client_id or str(setting("dji_client_id", "")),
            "username": username if username is not None else setting("dji_username", ""),
            "password": password if password is not None else setting("dji_password", ""),
            "paho_installed": paho_installed,
            "aircraft_count": len([sn for sn in aircraft if sn]),
            "aircraft": aircraft,
            "pending_calibration": len(getattr(c, "_pending_calibration", {}) or {}) if c else 0,
            "connected": bool(getattr(c, "_connected", False)) if c else False,
        }

    # -------------------------------------------------------------- resolve
    def _resolve(self, item: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
        """Return (value, resolved_file_path) for one checklist item."""
        source = str(item.get("source") or "")
        key = str(item.get("key") or "")
        if source == "runtime":
            return _dig(self._runtime, key), None
        if source == "constant":
            return item.get("value"), None
        if source.startswith("config:"):
            name = source.split(":", 1)[1]
            return _dig(self._configs.get(name, {}), key), str(_CONFIG_FILES.get(name, ""))
        if source.startswith("backend_path:"):
            raw = _dig(self._configs.get("wpml", {}), source.split(":", 1)[1])
            if not raw:
                return "", None
            path = Path(str(raw))
            if not path.is_absolute():
                path = BACKEND_ROOT / path
            return str(path), str(path)
        if source.startswith("runtime_path:"):
            attr = source.split(":", 1)[1]
            value = getattr(self.connector, attr, None) if self.connector else None
            fallback = BACKEND_ROOT / "config" / str(item.get("key") or "")
            return str(value or fallback), str(value or fallback)
        return None, None

    # --------------------------------------------------------------- verdict
    def _verdict(self, item: Dict[str, Any], value: Any) -> Tuple[str, str]:
        check = str(item.get("check") or "manual")
        expected = item.get("expected")
        placeholders = set(self.checklist.get("placeholder_values") or [])
        text = "" if value is None else str(value).strip()

        if check == "manual":
            return "manual", "需在真机联调时人工核对"
        if check == "equals":
            if value == expected:
                return "pass", f"当前值 = {expected}"
            return "fail", f"期望 {expected}，当前 {text or '(空)'}"
        if check == "not_placeholder":
            if text in placeholders or "mock" in text.lower():
                return "fail", f"仍是占位值：{text or '(空)'}"
            return "pass", "已替换为真实值"
        if check == "not_local_host":
            if text.lower() in _LOCAL_HOSTS:
                return "fail", f"仍是本地地址：{text or '(空)'}"
            return "pass", text
        if check == "truthy":
            return ("pass", "已启用") if bool(value) else ("fail", "未启用或为空")
        if check == "falsy":
            return ("pass", "未启用") if not bool(value) else ("fail", f"当前为 {text}")
        if check == "configured":
            return ("pass", "已配置") if text else ("fail", "未配置")
        if check == "positive_number":
            try:
                return ("pass", f"{int(value)} 架飞机") if int(value) > 0 else (
                    "fail", "未绑定飞机")
            except (TypeError, ValueError):
                return "fail", f"非法数值：{text or '(空)'}"
        if check == "tls_port_match":
            ports = _dig(self._configs.get("tls", {}), "tls.ports") or []
            if isinstance(ports, list) and value in ports:
                return "pass", f"端口 {value} 在 tls.ports 中"
            return "fail", f"端口 {value} 不在 tls.ports={ports}"
        if check == "file_exists":
            if text and Path(text).is_file():
                return "pass", text
            return "fail", f"文件不存在：{text or '(空)'}"
        if check == "file_exists_if_set":
            if not text:
                return "warn", "未配置 CA 证书，真机建议使用平台下发的 CA"
            if Path(text).is_file():
                return "pass", text
            return "fail", f"CA 文件不存在：{text}"
        if check == "client_cert_pair":
            tls = self._configs.get("tls", {}).get("tls", {}) or {}
            cert = str(tls.get("certfile") or "").strip()
            key = str(tls.get("keyfile") or "").strip()
            auth = str(tls.get("client_auth") or "none").lower()
            mutual = auth in {"required", "require", "mutual", "yes", "true"}
            if mutual:
                if not cert or not key:
                    return "fail", "client_auth 要求双向认证，但证书/私钥未配置"
                if not Path(cert).is_file() or not Path(key).is_file():
                    return "fail", "证书或私钥文件不存在"
                return "pass", "证书/私钥齐备"
            if bool(cert) != bool(key):
                return "warn", "证书与私钥只配置了一个"
            return "pass", "未启用双向认证"
        if check == "max_altitude":
            routes = value if isinstance(value, list) else []
            alts = [
                float(wp.get("alt", 0)) for route in routes
                if isinstance(route, dict)
                for wp in (route.get("waypoints") or [])
                if isinstance(wp, dict) and wp.get("alt") is not None
            ]
            ceiling = float(expected or 0)
            if alts and max(alts) <= ceiling:
                return "pass", f"最高 {max(alts):.0f}m ≤ {ceiling:.0f}m"
            return "fail", f"最高 {max(alts) if alts else 'N/A'}m 超过 {ceiling:.0f}m"
        if check == "dir_writable":
            if not text:
                return "fail", "输出目录未配置"
            try:
                path = Path(text)
                path.mkdir(parents=True, exist_ok=True)
                if os.access(str(path), os.W_OK):
                    return "pass", str(path)
                return "fail", f"目录不可写：{path}"
            except OSError as exc:
                return "fail", f"目录不可用：{exc}"
        return "manual", f"未知检查类型：{check}"

    # ---------------------------------------------------------------- report
    def report(self) -> Dict[str, Any]:
        groups: List[Dict[str, Any]] = []
        counts = {"pass": 0, "warn": 0, "fail": 0, "manual": 0}
        blocking: List[str] = []
        advisories: List[str] = []

        for group in self.checklist.get("groups") or []:
            if not isinstance(group, dict):
                continue
            items_out: List[Dict[str, Any]] = []
            for item in group.get("items") or []:
                if not isinstance(item, dict):
                    continue
                value, config_file = self._resolve(item)
                secret = bool(item.get("secret")) or str(item.get("id")) in _SECRET_FIELDS
                display = (
                    ("已配置" if str(value or "").strip() else "未配置")
                    if secret else value
                )
                status, detail = self._verdict(item, value)
                counts[status] = counts.get(status, 0) + 1
                if status == "fail":
                    blocking.append(str(item.get("id")))
                elif status == "warn":
                    advisories.append(str(item.get("id")))
                items_out.append({
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("id"),
                    "source": item.get("source"),
                    "config_file": config_file,
                    "value": display,
                    "expected": item.get("expected"),
                    "status": status,
                    "detail": detail,
                    "verify": item.get("verify", ""),
                    "secret": secret,
                })
            groups.append({
                "id": group.get("id"),
                "title": group.get("title") or group.get("id"),
                "description": group.get("description", ""),
                "items": items_out,
            })

        total = sum(counts.values())
        return {
            "version": self.checklist.get("version", "1.0"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": self._runtime["mode"],
            "connector_mounted": self.connector is not None,
            "summary": {
                "total": total,
                **counts,
                "blocking": blocking,
                "advisories": advisories,
                "ready": counts["fail"] == 0,
            },
            "groups": groups,
            "runtime": {
                "mode": self._runtime["mode"],
                "gateway_sn": self._runtime["gateway_sn"],
                "broker_host": self._runtime["broker_host"],
                "broker_port": self._runtime["broker_port"],
                "aircraft_count": self._runtime["aircraft_count"],
                "connected": self._runtime["connected"],
            },
        }

    def markdown(self, report: Optional[Dict[str, Any]] = None) -> str:
        """Render the report as a checkable Markdown checklist."""
        r = report or self.report()
        s = r["summary"]
        icon = {"pass": "[x]", "warn": "[!]", "fail": "[ ]", "manual": "[ ]"}
        lines = [
            "# DJI 真机联调核对清单",
            "",
            f"- 生成时间：{r['generated_at']}",
            f"- 运行模式：{r['mode']}（连接器挂载：{'是' if r['connector_mounted'] else '否'}）",
            f"- 结果：可联调 **{'是' if s['ready'] else '否'}** · "
            f"通过 {s['pass']} · 警告 {s['warn']} · 失败 {s['fail']} · 人工 {s['manual']}",
            "",
        ]
        if s["blocking"]:
            lines += ["## 阻塞项", ""] + [f"- `{i}`" for i in s["blocking"]] + [""]
        for group in r["groups"]:
            lines += [f"## {group['title']}", ""]
            if group.get("description"):
                lines += [group["description"], ""]
            for item in group["items"]:
                value = item.get("value")
                value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
                lines.append(
                    f"- {icon.get(item['status'], '[ ]]')} **{item['title']}** "
                    f"({item['id']}) — `{value}` · {item['detail']}"
                )
                if item.get("verify"):
                    lines.append(f"  - 真机核对：{item['verify']}")
            lines.append("")
        return "\n".join(lines)
