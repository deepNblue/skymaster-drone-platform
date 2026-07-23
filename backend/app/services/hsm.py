"""HSM (Hardware Security Module) abstraction — R21.

Design goal
-----------

R20 landed SM2 signing that reads private keys from environment variables.
That is fine for dev / small pilot, but 等保三级 hard-requires that in
production, private key material lives in an HSM / cipher machine
(密码机) so operators never see the raw private hex. This module exposes a
stable *signer protocol* that both:

  * ``EnvHexSigner``  — current impl, private key from env (dev / pilot);
  * ``PKCS11Signer``  — placeholder for real HSM (深信服 / Thales / 三未信安
                         国密卡等), implemented lazily when a device is
                         actually available.

Callers do not care which backend serves them; ``sm2_signer.sign_hash()``
just picks the highest-priority available backend at call time.

This keeps the R20 code path unchanged and adds a strict boundary so
future HSM integration is a drop-in without touching audit middleware.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignResult:
    signature_hex: str
    key_id: str
    backend: str  # "env" | "pkcs11" | "cloud-kms" | ...


class SM2SignerBackend(ABC):
    """Base protocol every signer backend must implement."""

    #: Higher priority backends are tried first when signing.
    priority: int = 0

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def sign(self, record_id: str, curr_hash: str, ts: str) -> Optional[SignResult]:
        """Return ``None`` if this backend cannot sign right now
        (missing key material, HSM offline, etc.) — the caller will try
        the next backend."""

    @abstractmethod
    def verify(
        self,
        record_id: str,
        curr_hash: str,
        ts: str,
        signature_hex: str,
        key_id: str,
    ) -> bool: ...


class PKCS11Signer(SM2SignerBackend):
    """Placeholder PKCS#11 signer. Real drivers are provided by the HSM
    vendor (深信服 SSF, 三未信安, 得安, Thales等). We keep the class here
    so ops can flip a single env switch to route new signatures through
    the HSM once a device is provisioned; verifies fall back to the
    env-hex backend for legacy audit rows signed before HSM roll-in."""

    priority = 100  # prefer HSM when available

    def name(self) -> str:
        return "pkcs11"

    def is_available(self) -> bool:
        # A real integration checks the driver + slot login. We keep it
        # off unless explicitly opted in AND the driver lib is importable.
        if os.getenv("SM2_HSM_ENABLED", "0") not in ("1", "true", "TRUE"):
            return False
        try:
            import PyKCS11  # type: ignore  # noqa: F401
        except Exception:
            return False
        return True

    def sign(self, record_id: str, curr_hash: str, ts: str) -> Optional[SignResult]:
        if not self.is_available():
            return None
        # NOTE: real HSM signing is out of scope for R21 — this is the
        # tie-in point. When a device is provisioned in prod:
        #   1. resolve slot via SM2_HSM_SLOT env
        #   2. login with SM2_HSM_PIN
        #   3. locate private key labelled SM2_HSM_KEY_LABEL
        #   4. call C_Sign with mechanism = CKM_SM3_SM2 or CKM_SM2
        # For now we return None so the fallback backend takes over.
        log.info("PKCS11 signer opted-in but not yet implemented; falling back")
        return None

    def verify(self, *args, **kwargs) -> bool:
        # HSM verify is optional — env backend can verify HSM-issued sigs
        # as long as the corresponding public key was registered via
        # SM2_KEYS_JSON. Keep this as a no-op.
        return False


class EnvHexSigner(SM2SignerBackend):
    """R20 baseline signer — reads keys from env vars. Kept as the
    always-available fallback so soft-fail semantics are preserved."""

    priority = 10

    def name(self) -> str:
        return "env-hex"

    def is_available(self) -> bool:
        # Import lazily to avoid an import cycle at module load.
        from app.services import sm2_signer

        return sm2_signer.is_enabled()

    def sign(self, record_id: str, curr_hash: str, ts: str) -> Optional[SignResult]:
        from app.services import sm2_signer

        res = sm2_signer.sign_hash(record_id, curr_hash, ts)
        if res is None:
            return None
        sig, kid = res
        return SignResult(signature_hex=sig, key_id=kid, backend=self.name())

    def verify(
        self,
        record_id: str,
        curr_hash: str,
        ts: str,
        signature_hex: str,
        key_id: str,
    ) -> bool:
        from app.services import sm2_signer

        return sm2_signer.verify(record_id, curr_hash, ts, signature_hex, key_id)


_BACKENDS_CACHE: list[SM2SignerBackend] | None = None


def _backends() -> list[SM2SignerBackend]:
    """Ordered by priority (highest first). Cached at module load."""
    global _BACKENDS_CACHE
    if _BACKENDS_CACHE is None:
        _BACKENDS_CACHE = sorted(
            [PKCS11Signer(), EnvHexSigner()],
            key=lambda b: -b.priority,
        )
    return _BACKENDS_CACHE


def _reset_cache() -> None:  # test hook
    global _BACKENDS_CACHE
    _BACKENDS_CACHE = None


def preferred_backend() -> str:
    for b in _backends():
        if b.is_available():
            return b.name()
    return "none"


def sign_via_best_backend(
    record_id: str, curr_hash: str, ts: str
) -> Optional[SignResult]:
    """Try backends in priority order; first one that returns a signature wins."""
    for b in _backends():
        if not b.is_available():
            continue
        res = b.sign(record_id, curr_hash, ts)
        if res is not None:
            return res
    return None


def verify_via_any_backend(
    record_id: str,
    curr_hash: str,
    ts: str,
    signature_hex: str,
    key_id: str,
) -> bool:
    for b in _backends():
        if b.verify(record_id, curr_hash, ts, signature_hex, key_id):
            return True
    return False


def hsm_status() -> dict:
    """Small helper for the admin endpoint."""
    return {
        "backends": [
            {"name": b.name(), "priority": b.priority, "available": b.is_available()}
            for b in _backends()
        ],
        "active_backend": preferred_backend(),
    }
