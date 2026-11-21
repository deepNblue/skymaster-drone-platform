"""T7.1 — RPA bridge for属地审批 (fill-a-form-behind-a-login authorities).

Some domestic authorities (city 公安, 文旅, provincial 空管) don't have
public APIs; the way an operator actually files is by logging into their
web portal and filling an HTML/e-Form. This module wraps that dance
behind a stable adapter interface so the fan-out router can treat RPA
authorities the same as native-API ones.

Adapter contract
----------------
Each RPADriver implements:

    submit(payload) -> RPAJob                 # kicks the browser bot
    poll(job_id)   -> RPAJob                 # returns current status
    cancel(job_id) -> bool                   # best-effort abort

Status vocabulary is the *authority-row* one:
    pending → submitted → approving → approved | rejected | skipped

Drivers included here
---------------------
* MockRPADriver — for tests. Deterministic; every 3rd job auto-approves
  after ~2 polls, others hover in ``approving``. No I/O.
* ShenzhenATCEFormDriver — stub. Records the payload verbatim, marks
  the job ``submitted``, then transitions to ``approving`` on poll.
  Real Playwright integration lives in a future sprint (T7.2).

Callback pathway
----------------
External RPA workers (Docker-hosted Playwright, staff-desk browser
extension, or the mock) POST to /api/v1/approvals/rpa-callback with an
HMAC-signed body:

    {job_id, status, external_ref?, reject_reason?, evidence?}

The endpoint verifies HMAC-SHA256 over the sorted-JSON body using the
shared secret env ``RPA_WEBHOOK_SECRET`` and, on success, updates the
matching FlightApprovalAuthority row + emits a timeline event.

Idempotency
-----------
Dispatch is keyed on (approval_id, authority_code). Calling twice with
the same tuple returns the existing RPAJob instead of spawning a new
one — reflects real-world "user hits button twice" behavior.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol
from uuid import UUID, uuid4


@dataclass
class RPAJob:
    """One RPA task. Lifecycle:

        queued → running → submitted → approving → approved | rejected | error
    """

    job_id: str
    approval_id: str
    authority_code: str
    driver: str
    status: str = "queued"
    external_ref: Optional[str] = None
    reject_reason: Optional[str] = None
    poll_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)

    def touch(self):
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class RPADriver(Protocol):
    name: str

    async def submit(self, payload: dict) -> RPAJob: ...
    async def poll(self, job: RPAJob) -> RPAJob: ...
    async def cancel(self, job: RPAJob) -> bool: ...


# ---------------------------------------------------------------------------
# Deterministic mock — for CI, local dev, and the smoke test suite.
# ---------------------------------------------------------------------------


class MockRPADriver:
    """Auto-progresses every job through the lifecycle. Deterministic.

    On submit:  status = 'submitted', external_ref = MOCK-<8>
    On poll 1:  status = 'approving'
    On poll 2:  status = 'approved' (job_id ends with even hex) or
                          'rejected' with reason (odd hex)
    """

    name = "mock"

    async def submit(self, payload: dict) -> RPAJob:
        job = RPAJob(
            job_id=f"mock-{uuid4().hex[:12]}",
            approval_id=str(payload.get("approval_id")),
            authority_code=str(payload.get("authority_code")),
            driver=self.name,
            status="submitted",
            external_ref=f"MOCK-{uuid4().hex[:8].upper()}",
            payload=payload,
        )
        return job

    async def poll(self, job: RPAJob) -> RPAJob:
        job.poll_count += 1
        job.touch()
        if job.poll_count == 1:
            job.status = "approving"
        elif job.poll_count >= 2:
            # deterministic decision from job_id hex tail
            tail = int(job.job_id[-1], 16)
            if tail % 2 == 0:
                job.status = "approved"
                job.evidence = {"mock_evidence": "auto-approve"}
            else:
                job.status = "rejected"
                job.reject_reason = "mock: rejected by driver"
        return job

    async def cancel(self, job: RPAJob) -> bool:
        job.status = "cancelled"
        job.touch()
        return True


# ---------------------------------------------------------------------------
# Shenzhen ATC e-Form stub — Playwright integration in T7.2.
# ---------------------------------------------------------------------------


class ShenzhenATCEFormDriver:
    """Placeholder for real Playwright driver.

    In production this would drive a headless Chromium against
    https://uom.caac.gov.cn/  (or the属地空管 URL) to fill the e-Form.
    Right now it records the payload and leaves the job in ``submitted``
    so the operator can manually confirm — safer default than
    fake-approving.
    """

    name = "shenzhen_atc_eform"

    async def submit(self, payload: dict) -> RPAJob:
        # A real driver would open a browser here. Playwright launch is
        # 500ms even without navigation, so we keep it async-friendly.
        return RPAJob(
            job_id=f"sz-{uuid4().hex[:10]}",
            approval_id=str(payload.get("approval_id")),
            authority_code=str(payload.get("authority_code")),
            driver=self.name,
            status="submitted",
            payload=payload,
        )

    async def poll(self, job: RPAJob) -> RPAJob:
        job.poll_count += 1
        job.touch()
        # We can only mark 'approving' here; final decision comes
        # via signed webhook when the real portal notifies us.
        if job.poll_count >= 1 and job.status == "submitted":
            job.status = "approving"
        return job

    async def cancel(self, job: RPAJob) -> bool:
        job.status = "cancelled"
        job.touch()
        return True


# ---------------------------------------------------------------------------
# Bridge (registry + dispatch) — module-level singleton.
# ---------------------------------------------------------------------------


class RPABridge:
    """Registers drivers, dispatches jobs, and holds per-authority
    dedup. In-memory for MVP; a future v2.1 sprint can back it with
    Redis/Postgres for HA across pods.
    """

    def __init__(self) -> None:
        self._drivers: dict[str, RPADriver] = {}
        self._jobs: dict[str, RPAJob] = {}                # job_id → job
        self._by_key: dict[tuple[str, str], str] = {}     # (approval,authority) → job_id
        self._lock = asyncio.Lock()

    def register(self, driver: RPADriver) -> None:
        self._drivers[driver.name] = driver

    def route(self, authority_code: str) -> RPADriver:
        """Return the driver that handles this authority code.

        Convention:
          * shenzhen_atc → shenzhen_atc_eform (real portal)
          * default RPA authorities (local_police / tourism / atc) → mock
        """
        # Explicit routes take precedence.
        overrides = {
            "shenzhen_atc": "shenzhen_atc_eform",
        }
        driver_name = overrides.get(authority_code, "mock")
        driver = self._drivers.get(driver_name)
        if not driver:
            raise KeyError(f"No RPA driver registered for {driver_name!r}")
        return driver

    async def dispatch(
        self,
        approval_id: str,
        authority_code: str,
        payload: dict,
    ) -> RPAJob:
        """Idempotent: same (approval, authority) → same job.

        payload is passed through to the driver; we append the two IDs
        so drivers don't have to fish them out of caller code.
        """
        key = (approval_id, authority_code)
        async with self._lock:
            job_id = self._by_key.get(key)
            if job_id and job_id in self._jobs:
                return self._jobs[job_id]

            driver = self.route(authority_code)
            full_payload = {
                **payload,
                "approval_id": approval_id,
                "authority_code": authority_code,
            }
            job = await driver.submit(full_payload)
            self._jobs[job.job_id] = job
            self._by_key[key] = job.job_id
            return job

    async def poll(self, job_id: str) -> Optional[RPAJob]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        driver = self._drivers.get(job.driver)
        if not driver:
            return job
        return await driver.poll(job)

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        driver = self._drivers.get(job.driver)
        if not driver:
            return False
        return await driver.cancel(job)

    def get(self, job_id: str) -> Optional[RPAJob]:
        return self._jobs.get(job_id)

    def get_by_key(self, approval_id: str, authority_code: str) -> Optional[RPAJob]:
        key = (approval_id, authority_code)
        job_id = self._by_key.get(key)
        return self._jobs.get(job_id) if job_id else None

    # For tests --------------------------------------------------------------

    def _reset(self) -> None:
        self._jobs.clear()
        self._by_key.clear()


# ---------------------------------------------------------------------------
# Callback signature — HMAC-SHA256 over the canonical JSON body.
# ---------------------------------------------------------------------------


def canonical_body(body: dict) -> bytes:
    """Sort keys + no-whitespace JSON so the sender and receiver hash
    the exact same bytes.
    """
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_body(body: dict, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), canonical_body(body), hashlib.sha256,
    ).hexdigest()


def verify_signature(body: dict, provided: str, secret: str) -> bool:
    expected = sign_body(body, secret)
    return hmac.compare_digest(expected, provided)


# ---------------------------------------------------------------------------
# Module-level singleton, seeded with the two drivers.
# ---------------------------------------------------------------------------

_bridge: Optional[RPABridge] = None


def get_bridge() -> RPABridge:
    global _bridge
    if _bridge is None:
        b = RPABridge()
        b.register(MockRPADriver())
        b.register(ShenzhenATCEFormDriver())
        _bridge = b
    return _bridge
