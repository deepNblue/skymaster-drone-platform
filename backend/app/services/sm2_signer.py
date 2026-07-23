"""SM2 digital signature service — R21 Step F.

Adds a non-repudiation layer on top of the existing R18 tamper-evident
hash chain. Where the hash chain proves the *sequence* hasn't been
altered, an SM2 signature over each row's ``curr_hash`` proves who
witnessed that hash — a third party can verify it offline with just
the platform's public key.

Design
------

* **Key material** lives on disk (env-configured), never in DB:
    - ``SM2_PRIVATE_KEY_HEX`` (32 bytes = 64 hex chars)
    - ``SM2_PUBLIC_KEY_HEX``  (64 bytes = 128 hex chars, uncompressed)

  Missing keys → the module operates in **soft-fail** mode: sign
  returns ``None`` and callers continue as before. This keeps the
  platform bootable on dev boxes without private key material.

* **What we sign**: the canonical byte string
    ``sm2|v1|<record_id>|<curr_hash>|<timestamp>``
  so both hash chain and signature can be independently verified.

* **Rotation**: keys are versioned via ``SM2_KEY_ID`` (default ``"v1"``);
  the signature record stores the ID so future rotations don't invalidate
  old signatures — verification looks up the key set by ID.

* **Public API**:
    - ``sign_hash(record_id, curr_hash, ts) -> (signature_hex, key_id) | None``
    - ``verify(record_id, curr_hash, ts, signature_hex, key_id) -> bool``
    - ``export_public_pem(key_id) -> str``  (for external verifiers)
    - ``is_enabled() -> bool``

Deterministic across POSIX; uses the ``gmssl`` package (pure Python).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


_DEFAULT_KEY_ID = "v1"
# 等保三级要求密钥定期轮换 · SM2 通常 90 天，允许 env 覆盖
_DEFAULT_KEY_LIFETIME_DAYS = 90


@dataclass(frozen=True)
class KeySet:
    """One versioned SM2 keypair."""

    key_id: str
    private_hex: str | None
    public_hex: str
    #: unix seconds; 0 means unknown / legacy
    created_at: float = 0.0
    #: True → new signs use this; False → verify-only (retired)
    active: bool = True
    #: seconds a key stays valid for signing before rotation is due
    lifetime_seconds: float = _DEFAULT_KEY_LIFETIME_DAYS * 86400

    def age_days(self) -> float:
        if self.created_at <= 0:
            return -1.0  # legacy / unknown
        return (time.time() - self.created_at) / 86400.0

    def rotation_due(self) -> bool:
        if not self.active or self.created_at <= 0:
            return False
        return (time.time() - self.created_at) > self.lifetime_seconds


def _canonical(record_id: str, curr_hash: str, ts: str) -> bytes:
    return f"sm2|v1|{record_id}|{curr_hash}|{ts}".encode("utf-8")


def _load_keys_from_env() -> dict[str, KeySet]:
    """Load keypairs from env. Supports:

    * simple env pair (``SM2_PRIVATE_KEY_HEX`` / ``SM2_PUBLIC_KEY_HEX``);
    * legacy multi-key JSON (``SM2_KEYS_JSON``); now accepts
      ``created_at`` / ``active`` / ``lifetime_days`` per entry to enable
      rotation & retirement semantics.
    * retirement list (``SM2_RETIRED_KEY_IDS`` — comma-separated) to mark
      an ID verify-only without editing the JSON blob.
    """
    priv = (os.getenv("SM2_PRIVATE_KEY_HEX") or "").strip()
    pub = (os.getenv("SM2_PUBLIC_KEY_HEX") or "").strip()
    kid = (os.getenv("SM2_KEY_ID") or _DEFAULT_KEY_ID).strip()
    try:
        default_lifetime_days = float(
            os.getenv("SM2_KEY_LIFETIME_DAYS") or _DEFAULT_KEY_LIFETIME_DAYS
        )
    except ValueError:
        default_lifetime_days = _DEFAULT_KEY_LIFETIME_DAYS

    default_created = 0.0
    _iso = (os.getenv("SM2_KEY_CREATED_AT") or "").strip()
    if _iso:
        try:
            from datetime import datetime

            default_created = datetime.fromisoformat(
                _iso.replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            log.warning("SM2_KEY_CREATED_AT malformed: %s", _iso)

    retired = {
        k.strip() for k in (os.getenv("SM2_RETIRED_KEY_IDS") or "").split(",") if k.strip()
    }

    keys: dict[str, KeySet] = {}
    if pub:
        # priv may be absent (verifier-only nodes).
        keys[kid] = KeySet(
            key_id=kid,
            private_hex=priv or None,
            public_hex=pub,
            created_at=default_created,
            active=(kid not in retired),
            lifetime_seconds=default_lifetime_days * 86400,
        )

    extra = os.getenv("SM2_KEYS_JSON")
    if extra:
        import json

        try:
            payload = json.loads(extra)
            for entry in payload if isinstance(payload, list) else []:
                if not isinstance(entry, dict):
                    continue
                eid = str(entry.get("key_id") or "").strip()
                epub = str(entry.get("public_hex") or "").strip()
                epriv = entry.get("private_hex") or None
                if not (eid and epub):
                    continue
                # created_at may be ISO string or unix seconds
                created = 0.0
                raw_ct = entry.get("created_at")
                if isinstance(raw_ct, (int, float)):
                    created = float(raw_ct)
                elif isinstance(raw_ct, str) and raw_ct.strip():
                    try:
                        from datetime import datetime

                        created = datetime.fromisoformat(
                            raw_ct.replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        log.warning("SM2_KEYS_JSON created_at malformed: %s", raw_ct)
                active = bool(entry.get("active", True)) and eid not in retired
                try:
                    lifetime = float(
                        entry.get("lifetime_days", default_lifetime_days)
                    ) * 86400
                except (TypeError, ValueError):
                    lifetime = default_lifetime_days * 86400
                keys[eid] = KeySet(
                    key_id=eid,
                    private_hex=epriv,
                    public_hex=epub,
                    created_at=created,
                    active=active,
                    lifetime_seconds=lifetime,
                )
        except Exception as exc:
            log.warning("SM2_KEYS_JSON malformed: %s", exc)
    return keys


# Cached at module load — cheap; can be reset by tests via ``_reset_cache``.
_KEYSET_CACHE: dict[str, KeySet] | None = None
_ACTIVE_KEY_ID: str | None = None


def _keys() -> dict[str, KeySet]:
    global _KEYSET_CACHE
    if _KEYSET_CACHE is None:
        _KEYSET_CACHE = _load_keys_from_env()
    return _KEYSET_CACHE


def active_key_id() -> str | None:
    """Which key we use when signing NEW records. Only returns keys that
    are marked ``active`` (retirement-aware) AND have a private half."""
    global _ACTIVE_KEY_ID
    if _ACTIVE_KEY_ID is not None:
        # Recheck the cached choice is still active; a rotation may have
        # retired it in-process.
        ks = _keys()
        if _ACTIVE_KEY_ID in ks and ks[_ACTIVE_KEY_ID].private_hex and ks[_ACTIVE_KEY_ID].active:
            return _ACTIVE_KEY_ID
        _ACTIVE_KEY_ID = None  # fall through to re-pick
    env = (os.getenv("SM2_KEY_ID") or _DEFAULT_KEY_ID).strip()
    ks = _keys()
    if env in ks and ks[env].private_hex and ks[env].active:
        _ACTIVE_KEY_ID = env
        return env
    # Fallback: first ACTIVE key with a private half.
    for kid, k in ks.items():
        if k.private_hex and k.active:
            _ACTIVE_KEY_ID = kid
            return kid
    return None


def is_enabled() -> bool:
    """True iff at least one keyset has a private key (i.e. we can sign)."""
    return active_key_id() is not None


def _reset_cache() -> None:  # test hook
    global _KEYSET_CACHE, _ACTIVE_KEY_ID
    _KEYSET_CACHE = None
    _ACTIVE_KEY_ID = None


# ---------------------------------------------------------------------------
# Sign / verify — thin wrapper around gmssl (soft-fails on missing lib)
# ---------------------------------------------------------------------------


def _client_for(key_id: str, *, need_private: bool):
    """Build a gmssl.sm2.CryptSM2 for the given key. Returns None if unusable."""
    try:
        from gmssl import sm2 as _sm2
    except Exception as exc:  # pragma: no cover
        log.info("gmssl unavailable, SM2 signing disabled: %s", exc)
        return None
    keys = _keys()
    if key_id not in keys:
        return None
    k = keys[key_id]
    if need_private and not k.private_hex:
        return None
    # gmssl requires both fields on the object; pass an empty string when
    # the private half is missing.
    return _sm2.CryptSM2(
        private_key=k.private_hex or "",
        public_key=k.public_hex,
    )


def sign_hash(record_id: str, curr_hash: str, ts: str) -> Optional[tuple[str, str]]:
    """Sign the canonical message. Returns ``(signature_hex, key_id)`` or
    ``None`` if signing is not configured / gmssl not available.

    Never raises — signing is best-effort so it can't break the caller.
    """
    kid = active_key_id()
    if kid is None:
        return None
    client = _client_for(kid, need_private=True)
    if client is None:
        return None
    try:
        msg = _canonical(record_id, curr_hash, ts)
        # gmssl's sign() uses a random k when random_hex_str is provided.
        rnd = os.urandom(32).hex()
        sig = client.sign(msg, rnd)
        if not isinstance(sig, str) or not sig:
            return None
        return sig, kid
    except Exception as exc:  # pragma: no cover
        log.warning("SM2 sign failed: %s", exc)
        return None


def verify(
    record_id: str,
    curr_hash: str,
    ts: str,
    signature_hex: str,
    key_id: str,
) -> bool:
    """Return True iff the signature verifies under the named key."""
    if not signature_hex or not key_id:
        return False
    client = _client_for(key_id, need_private=False)
    if client is None:
        return False
    try:
        msg = _canonical(record_id, curr_hash, ts)
        return bool(client.verify(signature_hex, msg))
    except Exception as exc:
        log.info("SM2 verify errored: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Key material export — for public verifier tooling
# ---------------------------------------------------------------------------


def known_key_ids() -> list[str]:
    return sorted(_keys().keys())


def key_info(key_id: str) -> dict | None:
    """Rich per-key metadata for admin/audit UI."""
    k = _keys().get(key_id)
    if k is None:
        return None
    return {
        "key_id": k.key_id,
        "has_private": bool(k.private_hex),
        "active": k.active,
        "created_at": k.created_at or None,
        "age_days": k.age_days() if k.created_at > 0 else None,
        "lifetime_days": k.lifetime_seconds / 86400.0,
        "rotation_due": k.rotation_due(),
    }


def rotation_status() -> dict:
    """Return a compact snapshot for /crypto/sm2/rotation."""
    ks = _keys()
    infos = [key_info(kid) for kid in sorted(ks.keys())]
    infos = [i for i in infos if i]
    active = active_key_id()
    return {
        "active_key_id": active,
        "any_rotation_due": any(i["rotation_due"] for i in infos),
        "keys": infos,
    }


def export_public_hex(key_id: str) -> str | None:
    k = _keys().get(key_id)
    if k is None:
        return None
    return k.public_hex


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh SM2 keypair (utility for ops scripts / tests).

    Returns ``(private_hex, public_hex)``. Public key is uncompressed
    (64 bytes = 128 hex chars). Raises RuntimeError if gmssl missing.
    """
    try:
        from gmssl.sm2 import CryptSM2 as _C
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"gmssl unavailable: {exc}") from exc
    # Simplest deterministic route — try the modern API, fall back to
    # the seed-based one shipped in older gmssl versions.
    try:
        # gmssl 3.2+ exposes a helper.
        from gmssl.func import random_hex  # type: ignore
    except Exception:
        random_hex = None  # noqa: N806
    priv_hex = (random_hex(64) if random_hex else os.urandom(32).hex()).lower()
    # Compute public key by scalar-multiplying the base point.
    # Fall back to gmssl's internal helper (available in ≥3.2.2).
    try:
        from gmssl.sm2 import _kg  # type: ignore
        Px, Py = _kg(int(priv_hex, 16), _C.ecc_table["g"])  # type: ignore[attr-defined]
        pub_hex = f"{Px:064x}{Py:064x}"
    except Exception:
        # Portable Python fallback — implement scalar mult ourselves using
        # the ec curve constants exposed by gmssl.
        from gmssl.sm2 import default_ecc_table
        p = int(default_ecc_table["p"], 16)
        a = int(default_ecc_table["a"], 16)
        gx = int(default_ecc_table["g"][:64], 16)
        gy = int(default_ecc_table["g"][64:], 16)

        def _inv(x, m):
            return pow(x, -1, m)

        def _add(P, Q):
            if P is None:
                return Q
            if Q is None:
                return P
            x1, y1 = P
            x2, y2 = Q
            if x1 == x2 and (y1 + y2) % p == 0:
                return None
            if P == Q:
                m = (3 * x1 * x1 + a) * _inv(2 * y1, p) % p
            else:
                m = (y2 - y1) * _inv((x2 - x1) % p, p) % p
            x3 = (m * m - x1 - x2) % p
            y3 = (m * (x1 - x3) - y1) % p
            return (x3, y3)

        def _mul(k, P):
            R = None
            while k:
                if k & 1:
                    R = _add(R, P)
                P = _add(P, P)
                k >>= 1
            return R

        Q = _mul(int(priv_hex, 16), (gx, gy))
        Qx, Qy = Q  # type: ignore[misc]
        pub_hex = f"{Qx:064x}{Qy:064x}"
    return priv_hex, pub_hex
