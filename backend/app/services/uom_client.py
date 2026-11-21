"""UOM (民航局无人机综合监管平台) 客户端 — v2.0 Track A A3.

Design contract
---------------

The real UOM API is not yet publicly documented for third-party
platforms (授权申请周期 6-12 周)。我们按 **公开可查的 UTMISS 规格**
预建接口，配三套可切换的 transport，让业务闭环先跑通、待授权到位后
只改配置 + 环境变量即可切真实接口。

三条通道 (per §3.14 & ROADMAP.md A3):
1. **实名登记同步**  — POST /uom/v1/pilots, POST /uom/v1/aircrafts
2. **适飞空域查询**  — POST /uom/v1/airspace/check（含 no-fly / 限飞 / 管控区）
3. **飞行活动申请** — POST /uom/v1/flight-plans + GET /flight-plans/{id}
4. **Remote ID 上报** — WebSocket / MQTT push channel（此处仅接口占位）

Runtime modes
-------------
* ``UOM_MODE=mock``  (default) — 内置确定性 mock 引擎，用于开发/测试/演示
* ``UOM_MODE=live``            — 走 httpx 到真实 UOM endpoint
* ``UOM_MODE=proxy``           — 走 SkyMaster 内网 UOM 网关（试点城市）

三种模式共享同一份 schema 与 ``UomClient`` facade；切换只影响 transport。

Configuration
-------------
所有业务参数（空域库、限高、审批策略、HTTP 端点、签名规则）集中在
``backend/config/uom.json``，可用 ``UOM_CONFIG`` 指向自定义文件。
敏感凭据（AK/SK、base URL）只读环境变量，绝不写进配置或日志。

Security
--------
* AK/SK 从 ``UOM_AK`` / ``UOM_SK`` 环境变量读取（名字在配置中声明）
* 请求签名：HMAC-SHA256 over ``METHOD|PATH|body_sha256|timestamp|nonce``
* 时间偏移容忍与 nonce 形状由配置声明；回调验签复用同一 canonical
* live/proxy 缺凭据或缺 base URL 时抛 ``UomConfigurationError``，不再静默
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

log = logging.getLogger(__name__)


UomMode = Literal["mock", "live", "proxy"]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "uom.json"
_CONFIG_CACHE: dict[str, dict[str, Any]] = {}


class UomConfigurationError(RuntimeError):
    """Selected mode lacks required configuration or credentials."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_uom_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load (and cache) the UOM config. ``UOM_CONFIG`` overrides the path."""
    key = str(Path(path)) if path else str(os.getenv("UOM_CONFIG") or DEFAULT_CONFIG_PATH)
    if key not in _CONFIG_CACHE:
        p = Path(key)
        if not p.is_file():
            raise UomConfigurationError(
                f"UOM 配置文件不存在：{key}（可用 UOM_CONFIG 指定路径）"
            )
        with p.open("r", encoding="utf-8") as fh:
            _CONFIG_CACHE[key] = json.load(fh)
    return _CONFIG_CACHE[key]


def reset_uom_config_cache() -> None:
    _CONFIG_CACHE.clear()


def get_mode(config: dict[str, Any] | None = None) -> UomMode:
    cfg = config or load_uom_config()
    m = cfg.get("mode", {})
    env_name = str(m.get("env", "UOM_MODE"))
    raw = str(os.getenv(env_name) or m.get("default") or "mock").strip().lower()
    allowed = m.get("allowed") or ["mock", "live", "proxy"]
    if raw not in allowed:
        raw = str(m.get("default") or "mock")
    return raw  # type: ignore[return-value]


def config_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Non-secret view of the effective runtime configuration."""
    cfg = config or load_uom_config()
    mode = get_mode(cfg)
    http = cfg.get("http", {})
    auth = cfg.get("auth", {})
    base_env = (http.get("base_url_env") or {}).get(mode, "")
    base_url_set = bool(os.getenv(base_env)) if base_env else False
    if mode == "mock":
        base_url_set = True
    return {
        "mode": mode,
        "authorized": mode != "mock",
        "config_version": cfg.get("version"),
        "base_url_env": base_env,
        "base_url_set": base_url_set,
        "ak_env": auth.get("ak_env"),
        "sk_env": auth.get("sk_env"),
        "ak_set": bool(os.getenv(str(auth.get("ak_env", "")))),
        "sk_set": bool(os.getenv(str(auth.get("sk_env", "")))),
        "paths": cfg.get("paths", {}),
        "signature": {
            "algorithm": cfg.get("signature", {}).get("algorithm"),
            "max_skew_s": cfg.get("signature", {}).get("max_skew_s"),
        },
        "note": (
            "UOM live 授权申请周期 6-12 周；mock 空域数据仅供演示，"
            "不能替代真实合规判断。"
        ),
    }


# ---------------------------------------------------------------------------
# Request signing (HMAC-SHA256) — canonical declared in config
# ---------------------------------------------------------------------------


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _header_names(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    names = (cfg or load_uom_config()).get("auth", {}).get("header_names", {})
    return {
        "ak": names.get("ak", "X-UOM-AK"),
        "timestamp": names.get("timestamp", "X-UOM-Timestamp"),
        "nonce": names.get("nonce", "X-UOM-Nonce"),
        "signature": names.get("signature", "X-UOM-Signature"),
        "body_hash": names.get("body_hash", "X-UOM-BodyHash"),
    }


def _canonical_bytes(
    cfg: dict[str, Any], method: str, path: str, body_hash: str,
    ts: str, nonce: str,
) -> bytes:
    template = cfg.get("signature", {}).get(
        "canonical", "{method}|{path}|{body_sha256}|{timestamp}|{nonce}"
    )
    return template.format(
        method=method.upper(), path=path, body_sha256=body_hash,
        timestamp=ts, nonce=nonce,
    ).encode("utf-8")


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    ak: str,
    sk: str,
    ts: str | None = None,
    nonce: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return signed headers dict to attach to a UOM request."""
    cfg = config or load_uom_config()
    hn = _header_names(cfg)
    ts = ts or str(int(time.time()))
    nonce = nonce or secrets.token_hex(8)
    body_hash = _sha256_hex(body or b"")
    canonical = _canonical_bytes(cfg, method, path, body_hash, ts, nonce)
    sig = hmac.new(sk.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return {
        hn["ak"]: ak,
        hn["timestamp"]: ts,
        hn["nonce"]: nonce,
        hn["signature"]: sig,
        hn["body_hash"]: body_hash,
    }


def verify_signature(
    *,
    method: str,
    path: str,
    body: bytes,
    ak: str,
    sk: str,
    headers: dict[str, str],
    max_skew_s: int | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Verify a signed callback / webhook from UOM."""
    cfg = config or load_uom_config()
    hn = _header_names(cfg)
    if max_skew_s is None:
        max_skew_s = int(cfg.get("signature", {}).get("max_skew_s", 60))
    if headers.get(hn["ak"]) != ak:
        return False, "ak mismatch"
    ts = headers.get(hn["timestamp"])
    if not ts or not ts.isdigit():
        return False, "missing timestamp"
    if abs(int(ts) - int(time.time())) > max_skew_s:
        return False, f"timestamp skew > {max_skew_s}s"
    nonce = headers.get(hn["nonce"])
    sig = headers.get(hn["signature"])
    if not (nonce and sig):
        return False, "missing nonce or signature"
    body_hash = _sha256_hex(body or b"")
    canonical = _canonical_bytes(cfg, method, path, body_hash, ts, nonce)
    expected = hmac.new(sk.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(sig, expected)
    return ok, "ok" if ok else "signature mismatch"


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PilotInfo:
    pilot_id: str            # 飞手实名 ID
    name: str
    id_card_hash: str        # 身份证号 SHA256（隐私保护，不明文发 UOM）
    license_no: Optional[str] = None
    license_class: Optional[str] = None  # 视距内 / 超视距 / 教员


@dataclass(frozen=True)
class AircraftInfo:
    reg_no: str              # UAS-XXXXX
    manufacturer: str
    model: str
    serial: str
    mtow_kg: float
    category: str            # 微 / 轻 / 小 / 中 / 大


@dataclass(frozen=True)
class AirspaceQuery:
    lat: float
    lng: float
    altitude_m: float
    radius_m: float = 500
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None


@dataclass(frozen=True)
class AirspaceVerdict:
    allowed: bool
    zone_type: str           # normal / limited / restricted / prohibited
    ceiling_m: Optional[float]
    reason: str
    references: list[str]    # 引用的空域文件号


@dataclass(frozen=True)
class FlightPlan:
    plan_id: str
    pilot_id: str
    aircraft_reg: str
    lat: float
    lng: float
    altitude_m: float
    start_ts: str
    end_ts: str
    purpose: str             # 巡线 / 测绘 / 应急 / ...
    contact_phone: str
    attachments: list[str]


@dataclass(frozen=True)
class UomAck:
    plan_id: str
    uom_ref_no: str          # UOM 返回的受理号
    status: str              # accepted / rejected / pending
    reviewer: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Rough haversine — sufficient for airspace containment."""
    import math
    r = 6371_000
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _first(data: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "ok"}


# ---------------------------------------------------------------------------
# Mock transport — deterministic, config-driven airspace library
# ---------------------------------------------------------------------------


class MockUomTransport:
    """Deterministic in-memory UOM backend for dev/test/demo."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_uom_config()
        mock_cfg = self.config.get("mock", {})
        airspace_cfg = mock_cfg.get("airspace", {})
        self._no_fly = [
            (str(z.get("name", "")), float(z["lat"]), float(z["lng"]),
             float(z["radius_m"]), str(z.get("doc_ref", "")))
            for z in airspace_cfg.get("no_fly_zones", [])
        ]
        self._limited = [
            (str(z.get("name", "")), float(z["lat"]), float(z["lng"]),
             float(z["radius_m"]), float(z["ceiling_m"]),
             str(z.get("doc_ref", "")))
            for z in airspace_cfg.get("ceiling_limited_zones", [])
        ]
        self._general_ceiling = float(airspace_cfg.get("general_ceiling_m", 120.0))
        self._general_ref = str(
            airspace_cfg.get("general_reference", "民用无人驾驶航空器飞行管理暂行条例 §16")
        )
        self._ref_prefix = str(mock_cfg.get("ref_prefix", "UOM"))
        self._pilot_prefix = str(mock_cfg.get("pilot_ref_prefix", "UP"))
        self._aircraft_prefix = str(mock_cfg.get("aircraft_ref_prefix", "UA"))
        self._pilots: dict[str, dict] = {}
        self._aircrafts: dict[str, dict] = {}
        self._plans: dict[str, dict] = {}

    # --- 实名登记 -------------------------------------------------------
    def upsert_pilot(self, pilot: PilotInfo) -> dict:
        self._pilots[pilot.pilot_id] = {
            "pilot_id": pilot.pilot_id, "name": pilot.name,
            "license_no": pilot.license_no, "license_class": pilot.license_class,
            "id_card_hash": pilot.id_card_hash,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"ok": True, "uom_pilot_ref": f"{self._pilot_prefix}-{pilot.pilot_id[:8]}"}

    def upsert_aircraft(self, ac: AircraftInfo) -> dict:
        self._aircrafts[ac.reg_no] = {
            "reg_no": ac.reg_no, "manufacturer": ac.manufacturer,
            "model": ac.model, "serial": ac.serial,
            "mtow_kg": ac.mtow_kg, "category": ac.category,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"ok": True, "uom_aircraft_ref": f"{self._aircraft_prefix}-{ac.reg_no}"}

    # --- 空域校验 -------------------------------------------------------
    def check_airspace(self, q: AirspaceQuery) -> AirspaceVerdict:
        for name, lat, lng, radius, doc in self._no_fly:
            if _distance_m(q.lat, q.lng, lat, lng) <= radius:
                return AirspaceVerdict(
                    allowed=False, zone_type="prohibited", ceiling_m=0.0,
                    reason=f"位于「{name}」禁飞区内", references=[doc],
                )
        for name, lat, lng, radius, ceiling, doc in self._limited:
            if _distance_m(q.lat, q.lng, lat, lng) <= radius:
                if q.altitude_m > ceiling:
                    return AirspaceVerdict(
                        allowed=False, zone_type="limited", ceiling_m=ceiling,
                        reason=f"「{name}」限高 {ceiling}m，申请 {q.altitude_m}m 超限",
                        references=[doc],
                    )
                return AirspaceVerdict(
                    allowed=True, zone_type="limited", ceiling_m=ceiling,
                    reason=f"「{name}」限高 {ceiling}m 内可飞", references=[doc],
                )
        if q.altitude_m > self._general_ceiling:
            return AirspaceVerdict(
                allowed=False, zone_type="normal", ceiling_m=self._general_ceiling,
                reason=f"非隔离空域 {self._general_ceiling:g}m 通用上限",
                references=[self._general_ref],
            )
        return AirspaceVerdict(
            allowed=True, zone_type="normal", ceiling_m=self._general_ceiling,
            reason=f"非管控区域，{self._general_ceiling:g}m 以下正常空域",
            references=[],
        )

    # --- 飞行计划提交 ---------------------------------------------------
    def submit_plan(self, plan: FlightPlan) -> UomAck:
        if plan.pilot_id not in self._pilots:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="", status="rejected",
                reviewer=None, valid_from=None, valid_to=None,
                reason="飞手未在 UOM 实名登记",
            )
        if plan.aircraft_reg not in self._aircrafts:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="", status="rejected",
                reviewer=None, valid_from=None, valid_to=None,
                reason="无人机未在 UOM 登记",
            )
        verdict = self.check_airspace(AirspaceQuery(
            lat=plan.lat, lng=plan.lng, altitude_m=plan.altitude_m,
            start_ts=plan.start_ts, end_ts=plan.end_ts,
        ))
        if not verdict.allowed:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="", status="rejected",
                reviewer="airspace-auto", valid_from=None, valid_to=None,
                reason=verdict.reason,
            )
        ref = (f"{self._ref_prefix}-"
               f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}")
        self._plans[ref] = {
            "plan": plan.__dict__, "verdict": verdict.__dict__,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        return UomAck(
            plan_id=plan.plan_id, uom_ref_no=ref, status="accepted",
            reviewer="uom-mock", valid_from=plan.start_ts, valid_to=plan.end_ts,
        )

    def get_plan(self, ref: str) -> dict | None:
        return self._plans.get(ref)


_MOCK_SINGLETON: MockUomTransport | None = None


def get_mock_transport(config: dict[str, Any] | None = None) -> MockUomTransport:
    global _MOCK_SINGLETON
    cfg = config or load_uom_config()
    if _MOCK_SINGLETON is None or _MOCK_SINGLETON.config is not cfg:
        _MOCK_SINGLETON = MockUomTransport(cfg)
    return _MOCK_SINGLETON


def reset_mock_transport() -> None:
    global _MOCK_SINGLETON
    _MOCK_SINGLETON = None


# ---------------------------------------------------------------------------
# HTTP transport — used by both live and proxy modes
# ---------------------------------------------------------------------------


class HttpUomTransport:
    """httpx-backed transport for live UOM / internal proxy gateways.

    ``client`` is injectable so tests can pass an ``httpx.Client`` with a
    ``MockTransport`` and exercise the full signed request path offline.
    """

    def __init__(
        self,
        mode: Literal["live", "proxy"],
        config: dict[str, Any] | None = None,
        client: Any | None = None,
    ) -> None:
        if mode not in ("live", "proxy"):
            raise ValueError("HttpUomTransport mode must be 'live' or 'proxy'")
        self.mode = mode
        self.config = config or load_uom_config()
        self._client = client

    @property
    def base_url(self) -> str:
        http_cfg = self.config.get("http", {})
        env_name = str((http_cfg.get("base_url_env") or {}).get(self.mode, ""))
        url = os.getenv(env_name) if env_name else ""
        if not url:
            url = str((http_cfg.get("fallback_base_url") or {}).get(self.mode, ""))
        if not url:
            raise UomConfigurationError(
                f"{self.mode} 模式需要设置 {env_name or 'base URL'} 环境变量"
                "（或在 config/uom.json 配 fallback_base_url）"
            )
        return url.rstrip("/")

    def _credentials(self) -> tuple[str, str]:
        auth = self.config.get("auth", {})
        ak_env = str(auth.get("ak_env", "UOM_AK"))
        sk_env = str(auth.get("sk_env", "UOM_SK"))
        ak, sk = os.getenv(ak_env), os.getenv(sk_env)
        if not ak or not sk:
            raise UomConfigurationError(
                f"{self.mode} 模式需要环境变量 {ak_env} 与 {sk_env}（凭据不得写入配置文件）"
            )
        return ak, sk

    def _map_status(self, value: Any) -> str:
        raw = str(value or "").strip()
        for status, candidates in (self.config.get("status_map") or {}).items():
            if raw in [str(c) for c in candidates]:
                return status
        return raw or "pending"

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx

        http_cfg = self.config.get("http", {})
        payload = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if body is not None else b""
        )
        ak, sk = self._credentials()
        headers = sign_request(
            method=method, path=path, body=payload, ak=ak, sk=sk, config=self.config,
        )
        headers["Content-Type"] = "application/json"
        url = self.base_url + path
        timeout = float(http_cfg.get("timeout_s", 10.0))
        retries = int(http_cfg.get("max_retries", 2))
        backoff = float(http_cfg.get("retry_backoff_s", 0.5))
        retry_status = {int(s) for s in http_cfg.get("retry_on_status", [])}
        verify = bool(http_cfg.get("verify_tls", True))

        client = self._client or httpx.Client(timeout=timeout, verify=verify)
        owns_client = self._client is None
        try:
            for attempt in range(retries + 1):
                try:
                    resp = client.request(
                        method, url,
                        content=payload if payload else None,
                        headers=headers, params=params,
                    )
                except httpx.TransportError as exc:
                    if attempt >= retries:
                        raise UomConfigurationError(
                            f"UOM {method} {path} 网络失败：{exc}"
                        ) from exc
                    time.sleep(backoff * (2 ** attempt))
                    continue
                if resp.status_code in retry_status and attempt < retries:
                    time.sleep(backoff * (2 ** attempt))
                    continue
                resp.raise_for_status()
                return resp.json() if resp.content else {}
        finally:
            if owns_client:
                client.close()
        return {}

    # --- transport surface (same shape as MockUomTransport) -------------
    def upsert_pilot(self, pilot: PilotInfo) -> dict:
        path = self.config["paths"]["register_pilot"]
        data = self._request("POST", path, body={
            "pilot_id": pilot.pilot_id, "name": pilot.name,
            "id_card_hash": pilot.id_card_hash,
            "license_no": pilot.license_no, "license_class": pilot.license_class,
        })
        return {
            "ok": _as_bool(_first(data, ("ok", "success"), True)),
            "uom_pilot_ref": _first(data, ("uom_pilot_ref", "ref", "pilot_id"), ""),
        }

    def upsert_aircraft(self, ac: AircraftInfo) -> dict:
        path = self.config["paths"]["register_aircraft"]
        data = self._request("POST", path, body={
            "reg_no": ac.reg_no, "manufacturer": ac.manufacturer,
            "model": ac.model, "serial": ac.serial,
            "mtow_kg": ac.mtow_kg, "category": ac.category,
        })
        return {
            "ok": _as_bool(_first(data, ("ok", "success"), True)),
            "uom_aircraft_ref": _first(
                data, ("uom_aircraft_ref", "ref", "reg_no"), ""
            ),
        }

    def check_airspace(self, q: AirspaceQuery) -> AirspaceVerdict:
        path = self.config["paths"]["check_airspace"]
        data = self._request("POST", path, body={
            "lat": q.lat, "lng": q.lng, "altitude_m": q.altitude_m,
            "radius_m": q.radius_m, "start_ts": q.start_ts, "end_ts": q.end_ts,
        })
        allowed = _as_bool(_first(data, ("allowed", "permitted", "pass"), False))
        return AirspaceVerdict(
            allowed=allowed,
            zone_type=str(_first(data, ("zone_type", "zoneType", "areaType"), "normal")),
            ceiling_m=_first(data, ("ceiling_m", "ceilingM", "height_limit")),
            reason=str(_first(data, ("reason", "message", "remark"), "")),
            references=list(_first(data, ("references", "refs", "doc_refs"), []) or []),
        )

    def submit_plan(self, plan: FlightPlan) -> UomAck:
        path = self.config["paths"]["submit_plan"]
        data = self._request("POST", path, body={
            "plan_id": plan.plan_id, "pilot_id": plan.pilot_id,
            "aircraft_reg": plan.aircraft_reg,
            "lat": plan.lat, "lng": plan.lng, "altitude_m": plan.altitude_m,
            "start_ts": plan.start_ts, "end_ts": plan.end_ts,
            "purpose": plan.purpose, "contact_phone": plan.contact_phone,
            "attachments": plan.attachments,
        })
        return UomAck(
            plan_id=plan.plan_id,
            uom_ref_no=str(_first(
                data, ("uom_ref_no", "ref_no", "acceptNo", "uomRefNo"), ""
            )),
            status=self._map_status(_first(data, ("status", "approvalStatus"))),
            reviewer=_first(data, ("reviewer", "approver")),
            valid_from=_first(data, ("valid_from", "validFrom", "start_ts")),
            valid_to=_first(data, ("valid_to", "validTo", "end_ts")),
            reason=_first(data, ("reason", "message", "remark")),
        )

    def get_plan(self, ref: str) -> dict | None:
        template = self.config["paths"]["get_plan"]
        path = template.format(ref=ref)
        data = self._request("GET", path)
        return data or None


# ---------------------------------------------------------------------------
# Public facade — mode-aware, always import this
# ---------------------------------------------------------------------------


class UomClient:
    """Unified public entry — always import this, not the transports."""

    def __init__(
        self,
        mode: UomMode | None = None,
        config: dict[str, Any] | None = None,
        transport: Any | None = None,
    ) -> None:
        self.config = config or load_uom_config()
        self.mode: UomMode = mode or get_mode(self.config)
        if transport is not None:
            self._transport = transport
        elif self.mode == "mock":
            self._transport = get_mock_transport(self.config)
        else:
            self._transport = HttpUomTransport(self.mode, self.config)

    def register_pilot(self, pilot: PilotInfo) -> dict:
        return self._transport.upsert_pilot(pilot)

    def register_aircraft(self, ac: AircraftInfo) -> dict:
        return self._transport.upsert_aircraft(ac)

    def check_airspace(self, q: AirspaceQuery) -> AirspaceVerdict:
        return self._transport.check_airspace(q)

    def submit_plan(self, plan: FlightPlan) -> UomAck:
        return self._transport.submit_plan(plan)

    def get_plan(self, uom_ref: str) -> dict | None:
        return self._transport.get_plan(uom_ref)


def hash_id_card(raw: str) -> str:
    """SHA256 of trimmed id card — used before ever putting it on the wire."""
    return _sha256_hex(raw.strip().encode("utf-8"))
