"""Compliance / 国密 gateway — sits between callers and the raw SM primitives.

Design goals:
  1. **Zero-cost when off.** ``gm_crypto_enabled=False`` (default) → every
     helper is a pass-through — no imports of sm_crypto, no allocations.
  2. **Selective by module.** ``gm_protect_modules`` lets ops enable
     encryption only for the audit log while keeping telemetry & session
     tables plaintext for latency.
  3. **Explicit modes.**  "off" | "hash" | "full"
      - off  → passthrough
      - hash → SM3 hash-chain for tamper evidence, no encryption
      - full → SM3 hash-chain + SM4 payload encryption
  4. **Deterministic key derivation** so dev/tests work with no config.

Callers use::

    from app.services.crypto_gateway import gm

    if gm.enabled_for("audit_log"):
        ct = gm.encrypt("audit_log", plaintext)
        h  = gm.chain_hash(prev_hash, plaintext)
    else:
        ct = plaintext
        h  = plaintext  # or skip
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Optional

from app.config import settings

# We only import sm_crypto inside methods so a fully-disabled deployment
# doesn't pay the (small) module-load cost.


class ComplianceGateway:
    """Runtime-tunable façade around SM3/SM4.

    Instances are cheap; a module-level singleton (`gm`) is fine for typical
    use, but tests may construct their own with custom settings.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
        sm4_key_hex: str | None = None,
        protect_modules: Iterable[str] | None = None,
    ) -> None:
        self._enabled = settings.gm_crypto_enabled if enabled is None else enabled
        self._mode = (mode or settings.gm_crypto_mode or "off").lower()
        self._sm4_key_hex = sm4_key_hex if sm4_key_hex is not None else settings.gm_sm4_key_hex
        raw = protect_modules if protect_modules is not None else settings.gm_protect_modules
        if isinstance(raw, str):
            self._modules: set[str] = {m.strip() for m in raw.split(",") if m.strip()}
        else:
            self._modules = set(raw)

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled and self._mode != "off"

    @property
    def mode(self) -> str:
        """One of ``off`` / ``hash`` / ``full``."""
        return self._mode if self._enabled else "off"

    def enabled_for(self, module: str) -> bool:
        """Return True only if 国密 is on AND this module is protected."""
        return self.enabled and module in self._modules

    def status(self) -> dict:
        """Introspection for /health and admin UI."""
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "modules": sorted(self._modules),
            "algo": {
                "hash": "SM3-256" if self.mode in ("hash", "full") else None,
                "cipher": "SM4-CBC" if self.mode == "full" else None,
            },
        }

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    @lru_cache(maxsize=1)
    def _sm4_key(self) -> bytes:
        if self._sm4_key_hex:
            key = bytes.fromhex(self._sm4_key_hex)
            if len(key) != 16:
                raise ValueError("gm_sm4_key_hex must be 32 hex chars (16 bytes)")
            return key
        # Dev/test fallback — derive from jwt_secret.
        from app.services.sm_crypto import sm3_hash
        return sm3_hash(("skymaster-gm:" + settings.jwt_secret).encode())[:16]

    # ------------------------------------------------------------------
    # High-level ops
    # ------------------------------------------------------------------

    def chain_hash(self, previous: bytes, payload: str | bytes, module: str = "audit_log") -> bytes:
        """Append-only SM3 hash chain. Returns raw 32-byte digest.

        When 国密 is off for this module, returns the previous hash unchanged
        (chain is not extended). Callers should check ``enabled_for`` first
        and skip persistence if they want zero storage overhead.
        """
        if not self.enabled_for(module) or self.mode not in ("hash", "full"):
            return previous
        from app.services.sm_crypto import sm3_chain
        return sm3_chain(previous, payload)

    def encrypt(self, module: str, plaintext: str | bytes) -> str | bytes:
        """SM4-CBC encrypt. Returns hex string for `str` input, raw bytes for `bytes` input.

        Passthrough when disabled or module not protected.
        """
        if not self.enabled_for(module) or self.mode != "full":
            return plaintext
        from app.services.sm_crypto import sm4_encrypt
        blob = sm4_encrypt(plaintext, self._sm4_key())
        return blob.hex() if isinstance(plaintext, str) else blob

    def decrypt(self, module: str, ciphertext: str | bytes) -> str | bytes:
        """Reverse of ``encrypt``. Passthrough when disabled.

        Handles legacy plaintext transparently — if the input doesn't look
        like an SM4 blob (bad length / not valid hex), returns it as-is so
        rows written before 国密 was turned on still decode.
        """
        if not self.enabled_for(module) or self.mode != "full":
            return ciphertext
        from app.services.sm_crypto import sm4_decrypt
        try:
            if isinstance(ciphertext, str):
                blob = bytes.fromhex(ciphertext)
                return sm4_decrypt(blob, self._sm4_key()).decode("utf-8")
            return sm4_decrypt(ciphertext, self._sm4_key())
        except Exception:
            # Fall back to passthrough on decode failure (mixed-era data).
            return ciphertext

    # ------------------------------------------------------------------
    # Runtime toggle (admin API)
    # ------------------------------------------------------------------

    def apply(
        self,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
        modules: Iterable[str] | None = None,
    ) -> dict:
        """Live-reconfigure without a process restart. Used by admin API."""
        if enabled is not None:
            self._enabled = bool(enabled)
        if mode is not None:
            if mode not in ("off", "hash", "full"):
                raise ValueError(f"unknown gm mode {mode!r}")
            self._mode = mode
        if modules is not None:
            self._modules = set(modules)
        # Reset key cache in case future env changes are supported.
        self._sm4_key.cache_clear()
        return self.status()


# Module-level singleton — imported by services / API.
gm = ComplianceGateway()
