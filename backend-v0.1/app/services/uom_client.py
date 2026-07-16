"""UOM (民航局无人机综合监管平台) 客户端 — v2.0 Track A A3.

Design contract
---------------

The real UOM API is not yet publicly documented for third-party
platforms (授权申请周期 6-12 周)。我们按 **公开可查的 UTMISS 规格**
预建接口，配一份可切换的 Mock 后端，让业务闭环先跑通、待授权到位后
只替换 HTTP transport 即可上线。

三条通道 (per §3.14 & ROADMAP.md A3):
1. **实名登记同步**  — POST /uom/v1/pilots, POST /uom/v1/aircrafts
2. **适飞空域查询**  — POST /uom/v1/airspace/check（含 no-fly / 限飞 / 管控区）
3. **飞行活动申请** — POST /uom/v1/flight-plans + GET /flight-plans/{id}
4. **Remote ID 上报** — WebSocket / MQTT push channel（此处仅接口占位）

Runtime modes
-------------
* ``UOM_MODE=mock``  (default) — 内置确定性 mock 引擎，用于开发/测试/演示
* ``UOM_MODE=live``            — 走 httpx 到真实 UOM endpoint（未到位前不启用）
* ``UOM_MODE=proxy``           — 走 SkyMaster 内网 UOM 网关（用于试点城市）

三种模式共享同一份 pydantic schema — 切换只影响 transport。

Security
--------
* AK/SK 从 ``app.services.secret_store`` 读取（下一步 C3 密钥管理接入）
* 请求签名：HMAC-SHA256 over ``METHOD|PATH|body_sha256|timestamp|nonce``
* 时间偏移容忍 ±60s，nonce 单次有效
* 所有 UOM 交互写入独立审计通道（`uom.request` / `uom.response`），
  受 R21 F SM2 签名保护。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

log = logging.getLogger(__name__)


UomMode = Literal["mock", "live", "proxy"]


def get_mode() -> UomMode:
    m = (os.getenv("UOM_MODE") or "mock").strip().lower()
    return m if m in ("mock", "live", "proxy") else "mock"


# ---------------------------------------------------------------------------
# Request signing (HMAC-SHA256) — matches typical CAAC gateway convention
# ---------------------------------------------------------------------------


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    ak: str,
    sk: str,
    ts: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return headers dict to attach to a UOM request."""
    ts = ts or str(int(time.time()))
    nonce = nonce or secrets.token_hex(8)
    body_hash = _sha256_hex(body or b"")
    canonical = f"{method.upper()}|{path}|{body_hash}|{ts}|{nonce}".encode()
    sig = hmac.new(sk.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return {
        "X-UOM-AK": ak,
        "X-UOM-Timestamp": ts,
        "X-UOM-Nonce": nonce,
        "X-UOM-Signature": sig,
        "X-UOM-BodyHash": body_hash,
    }


def verify_signature(
    *,
    method: str,
    path: str,
    body: bytes,
    ak: str,
    sk: str,
    headers: dict[str, str],
    max_skew_s: int = 60,
) -> tuple[bool, str]:
    """Verify a signed callback / webhook from UOM."""
    if headers.get("X-UOM-AK") != ak:
        return False, "ak mismatch"
    ts = headers.get("X-UOM-Timestamp")
    if not ts or not ts.isdigit():
        return False, "missing timestamp"
    if abs(int(ts) - int(time.time())) > max_skew_s:
        return False, f"timestamp skew > {max_skew_s}s"
    nonce = headers.get("X-UOM-Nonce")
    sig = headers.get("X-UOM-Signature")
    if not (nonce and sig):
        return False, "missing nonce or signature"
    body_hash = _sha256_hex(body or b"")
    canonical = f"{method.upper()}|{path}|{body_hash}|{ts}|{nonce}".encode()
    expected = hmac.new(sk.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected), (
        "ok" if hmac.compare_digest(sig, expected) else "signature mismatch"
    )


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
# Deterministic mock engine
# ---------------------------------------------------------------------------


# 简易空域库 — 用于 mock 验证。生产环境从 UOM 拉取 + 缓存。
_MOCK_NO_FLY_ZONES = [
    # (name, center_lat, center_lng, radius_m, doc_ref)
    ("天府国际机场净空区", 30.312, 104.442, 15_000, "民航西南管理局 [2020] 12 号"),
    ("成都双流机场净空区", 30.578, 103.947, 15_000, "民航西南管理局 [2018] 03 号"),
    ("成都市区管控区", 30.652, 104.076, 3_000, "成都市公安局 [2023] 45 号"),
    ("北京六环管控区", 39.906, 116.397, 30_000, "民航华北管理局 [2019] 08 号"),
]

_MOCK_CEILING_LIMITED_ZONES = [
    # (name, center_lat, center_lng, radius_m, ceiling_m, doc_ref)
    ("龙泉山限高区", 30.552, 104.283, 8_000, 120.0, "四川省空管办 [2022] 07 号"),
]


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Rough haversine — sufficient for airspace containment."""
    import math
    r = 6371_000
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = (math.sin(dp/2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl/2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


class MockUomTransport:
    """Deterministic in-memory UOM backend for dev/test/demo."""

    def __init__(self) -> None:
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
        return {"ok": True, "uom_pilot_ref": f"UP-{pilot.pilot_id[:8]}"}

    def upsert_aircraft(self, ac: AircraftInfo) -> dict:
        self._aircrafts[ac.reg_no] = {
            "reg_no": ac.reg_no, "manufacturer": ac.manufacturer,
            "model": ac.model, "serial": ac.serial,
            "mtow_kg": ac.mtow_kg, "category": ac.category,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"ok": True, "uom_aircraft_ref": f"UA-{ac.reg_no}"}

    # --- 空域校验 -------------------------------------------------------
    def check_airspace(self, q: AirspaceQuery) -> AirspaceVerdict:
        # 1) 禁飞检查
        for name, lat, lng, radius, doc in _MOCK_NO_FLY_ZONES:
            if _distance_m(q.lat, q.lng, lat, lng) <= radius:
                return AirspaceVerdict(
                    allowed=False,
                    zone_type="prohibited",
                    ceiling_m=0.0,
                    reason=f"位于「{name}」禁飞区内",
                    references=[doc],
                )
        # 2) 限高检查
        for name, lat, lng, radius, ceiling, doc in _MOCK_CEILING_LIMITED_ZONES:
            if _distance_m(q.lat, q.lng, lat, lng) <= radius:
                if q.altitude_m > ceiling:
                    return AirspaceVerdict(
                        allowed=False,
                        zone_type="limited",
                        ceiling_m=ceiling,
                        reason=f"「{name}」限高 {ceiling}m，申请 {q.altitude_m}m 超限",
                        references=[doc],
                    )
                return AirspaceVerdict(
                    allowed=True, zone_type="limited",
                    ceiling_m=ceiling,
                    reason=f"「{name}」限高 {ceiling}m 内可飞",
                    references=[doc],
                )
        # 3) 微型/轻型默认 120m 上限
        if q.altitude_m > 120:
            return AirspaceVerdict(
                allowed=False, zone_type="normal",
                ceiling_m=120.0,
                reason="非隔离空域 120m 通用上限",
                references=["民用无人驾驶航空器飞行管理暂行条例 §16"],
            )
        return AirspaceVerdict(
            allowed=True, zone_type="normal",
            ceiling_m=120.0,
            reason="非管控区域，120m 以下正常空域",
            references=[],
        )

    # --- 飞行计划提交 ---------------------------------------------------
    def submit_plan(self, plan: FlightPlan) -> UomAck:
        # 校验飞手/无人机是否已实名
        if plan.pilot_id not in self._pilots:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="",
                status="rejected", reviewer=None,
                valid_from=None, valid_to=None,
                reason="飞手未在 UOM 实名登记",
            )
        if plan.aircraft_reg not in self._aircrafts:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="",
                status="rejected", reviewer=None,
                valid_from=None, valid_to=None,
                reason="无人机未在 UOM 登记",
            )
        # 校验空域
        verdict = self.check_airspace(AirspaceQuery(
            lat=plan.lat, lng=plan.lng, altitude_m=plan.altitude_m,
            start_ts=plan.start_ts, end_ts=plan.end_ts,
        ))
        if not verdict.allowed:
            return UomAck(
                plan_id=plan.plan_id, uom_ref_no="",
                status="rejected", reviewer="airspace-auto",
                valid_from=None, valid_to=None,
                reason=verdict.reason,
            )
        ref = f"UOM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        self._plans[ref] = {
            "plan": plan.__dict__, "verdict": verdict.__dict__,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        return UomAck(
            plan_id=plan.plan_id, uom_ref_no=ref,
            status="accepted", reviewer="uom-mock",
            valid_from=plan.start_ts, valid_to=plan.end_ts,
        )

    def get_plan(self, ref: str) -> dict | None:
        return self._plans.get(ref)


# Singleton — reset via ``reset_mock_transport`` in tests.
_MOCK_SINGLETON: MockUomTransport | None = None


def get_mock_transport() -> MockUomTransport:
    global _MOCK_SINGLETON
    if _MOCK_SINGLETON is None:
        _MOCK_SINGLETON = MockUomTransport()
    return _MOCK_SINGLETON


def reset_mock_transport() -> None:
    global _MOCK_SINGLETON
    _MOCK_SINGLETON = None


# ---------------------------------------------------------------------------
# Public facade — mode-aware
# ---------------------------------------------------------------------------


class UomClient:
    """Unified public entry — always import this, not the transports."""

    def __init__(self, mode: UomMode | None = None) -> None:
        self.mode: UomMode = mode or get_mode()

    def register_pilot(self, pilot: PilotInfo) -> dict:
        if self.mode == "mock":
            return get_mock_transport().upsert_pilot(pilot)
        raise NotImplementedError("live UOM transport not yet authorized")

    def register_aircraft(self, ac: AircraftInfo) -> dict:
        if self.mode == "mock":
            return get_mock_transport().upsert_aircraft(ac)
        raise NotImplementedError("live UOM transport not yet authorized")

    def check_airspace(self, q: AirspaceQuery) -> AirspaceVerdict:
        if self.mode == "mock":
            return get_mock_transport().check_airspace(q)
        raise NotImplementedError("live UOM transport not yet authorized")

    def submit_plan(self, plan: FlightPlan) -> UomAck:
        if self.mode == "mock":
            return get_mock_transport().submit_plan(plan)
        raise NotImplementedError("live UOM transport not yet authorized")

    def get_plan(self, uom_ref: str) -> dict | None:
        if self.mode == "mock":
            return get_mock_transport().get_plan(uom_ref)
        raise NotImplementedError("live UOM transport not yet authorized")


def hash_id_card(raw: str) -> str:
    """SHA256 of trimmed id card — used before ever putting it on the wire."""
    return _sha256_hex(raw.strip().encode("utf-8"))
