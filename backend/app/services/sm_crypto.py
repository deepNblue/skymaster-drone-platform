"""SM3 / SM4 pure-Python reference implementation for 等保 2.0 三级合规.

Implements only what SkyMaster needs:
  - SM3 hash (256-bit) — for log integrity digests
  - SM4 CBC/ECB block cipher (128-bit key/block) — for log payload encryption
    at rest

References: GB/T 32905-2016 (SM3), GB/T 32907-2016 (SM4). This is a
straightforward, spec-following implementation kept small and audit-able —
no C extensions, no external deps.

For production, swap ``sm3_hash`` and ``sm4_encrypt``/``sm4_decrypt`` for
a certified HSM/PKI backend; the shape of the API stays the same.
"""
from __future__ import annotations

import os
import struct
from typing import Union

# ============================================================
# SM3
# ============================================================

_SM3_IV = (
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
)


def _rotl(x: int, n: int) -> int:
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _sm3_cf(V: list[int], B: bytes) -> list[int]:
    W = list(struct.unpack(">16I", B))
    for j in range(16, 68):
        W.append(
            _p1(W[j - 16] ^ W[j - 9] ^ _rotl(W[j - 3], 15))
            ^ _rotl(W[j - 13], 7)
            ^ W[j - 6]
        )
    W1 = [W[j] ^ W[j + 4] for j in range(64)]

    A, B_, C, D, E, F, G, H = V
    for j in range(64):
        if j < 16:
            Tj = 0x79CC4519
            FF = A ^ B_ ^ C
            GG = E ^ F ^ G
        else:
            Tj = 0x7A879D8A
            FF = (A & B_) | (A & C) | (B_ & C)
            GG = (E & F) | ((~E) & 0xFFFFFFFF & G)
        SS1 = _rotl((_rotl(A, 12) + E + _rotl(Tj, j)) & 0xFFFFFFFF, 7)
        SS2 = SS1 ^ _rotl(A, 12)
        TT1 = (FF + D + SS2 + W1[j]) & 0xFFFFFFFF
        TT2 = (GG + H + SS1 + W[j]) & 0xFFFFFFFF
        D = C
        C = _rotl(B_, 9)
        B_ = A
        A = TT1
        H = G
        G = _rotl(F, 19)
        F = E
        E = _p0(TT2)

    return [
        (A ^ V[0]) & 0xFFFFFFFF,
        (B_ ^ V[1]) & 0xFFFFFFFF,
        (C ^ V[2]) & 0xFFFFFFFF,
        (D ^ V[3]) & 0xFFFFFFFF,
        (E ^ V[4]) & 0xFFFFFFFF,
        (F ^ V[5]) & 0xFFFFFFFF,
        (G ^ V[6]) & 0xFFFFFFFF,
        (H ^ V[7]) & 0xFFFFFFFF,
    ]


def sm3_hash(data: Union[bytes, str]) -> bytes:
    """Compute SM3-256 hash. Returns 32 raw bytes.

    >>> sm3_hash(b"abc").hex()
    '66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0'
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    n = len(data)
    m = data + b"\x80"
    # pad to 56 mod 64
    while len(m) % 64 != 56:
        m += b"\x00"
    m += struct.pack(">Q", n * 8)

    V = list(_SM3_IV)
    for i in range(0, len(m), 64):
        V = _sm3_cf(V, m[i:i + 64])
    return struct.pack(">8I", *V)


def sm3_hex(data: Union[bytes, str]) -> str:
    return sm3_hash(data).hex()


# ============================================================
# SM4
# ============================================================

_SM4_SBOX = bytes([
    0xD6, 0x90, 0xE9, 0xFE, 0xCC, 0xE1, 0x3D, 0xB7, 0x16, 0xB6, 0x14, 0xC2, 0x28, 0xFB, 0x2C, 0x05,
    0x2B, 0x67, 0x9A, 0x76, 0x2A, 0xBE, 0x04, 0xC3, 0xAA, 0x44, 0x13, 0x26, 0x49, 0x86, 0x06, 0x99,
    0x9C, 0x42, 0x50, 0xF4, 0x91, 0xEF, 0x98, 0x7A, 0x33, 0x54, 0x0B, 0x43, 0xED, 0xCF, 0xAC, 0x62,
    0xE4, 0xB3, 0x1C, 0xA9, 0xC9, 0x08, 0xE8, 0x95, 0x80, 0xDF, 0x94, 0xFA, 0x75, 0x8F, 0x3F, 0xA6,
    0x47, 0x07, 0xA7, 0xFC, 0xF3, 0x73, 0x17, 0xBA, 0x83, 0x59, 0x3C, 0x19, 0xE6, 0x85, 0x4F, 0xA8,
    0x68, 0x6B, 0x81, 0xB2, 0x71, 0x64, 0xDA, 0x8B, 0xF8, 0xEB, 0x0F, 0x4B, 0x70, 0x56, 0x9D, 0x35,
    0x1E, 0x24, 0x0E, 0x5E, 0x63, 0x58, 0xD1, 0xA2, 0x25, 0x22, 0x7C, 0x3B, 0x01, 0x21, 0x78, 0x87,
    0xD4, 0x00, 0x46, 0x57, 0x9F, 0xD3, 0x27, 0x52, 0x4C, 0x36, 0x02, 0xE7, 0xA0, 0xC4, 0xC8, 0x9E,
    0xEA, 0xBF, 0x8A, 0xD2, 0x40, 0xC7, 0x38, 0xB5, 0xA3, 0xF7, 0xF2, 0xCE, 0xF9, 0x61, 0x15, 0xA1,
    0xE0, 0xAE, 0x5D, 0xA4, 0x9B, 0x34, 0x1A, 0x55, 0xAD, 0x93, 0x32, 0x30, 0xF5, 0x8C, 0xB1, 0xE3,
    0x1D, 0xF6, 0xE2, 0x2E, 0x82, 0x66, 0xCA, 0x60, 0xC0, 0x29, 0x23, 0xAB, 0x0D, 0x53, 0x4E, 0x6F,
    0xD5, 0xDB, 0x37, 0x45, 0xDE, 0xFD, 0x8E, 0x2F, 0x03, 0xFF, 0x6A, 0x72, 0x6D, 0x6C, 0x5B, 0x51,
    0x8D, 0x1B, 0xAF, 0x92, 0xBB, 0xDD, 0xBC, 0x7F, 0x11, 0xD9, 0x5C, 0x41, 0x1F, 0x10, 0x5A, 0xD8,
    0x0A, 0xC1, 0x31, 0x88, 0xA5, 0xCD, 0x7B, 0xBD, 0x2D, 0x74, 0xD0, 0x12, 0xB8, 0xE5, 0xB4, 0xB0,
    0x89, 0x69, 0x97, 0x4A, 0x0C, 0x96, 0x77, 0x7E, 0x65, 0xB9, 0xF1, 0x09, 0xC5, 0x6E, 0xC6, 0x84,
    0x18, 0xF0, 0x7D, 0xEC, 0x3A, 0xDC, 0x4D, 0x20, 0x79, 0xEE, 0x5F, 0x3E, 0xD7, 0xCB, 0x39, 0x48,
])

_SM4_FK = (0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC)
_SM4_CK = tuple(
    (((i * 4 + 0) * 7) & 0xFF) << 24 |
    (((i * 4 + 1) * 7) & 0xFF) << 16 |
    (((i * 4 + 2) * 7) & 0xFF) << 8 |
    (((i * 4 + 3) * 7) & 0xFF)
    for i in range(32)
)


def _sm4_tau(a: int) -> int:
    return (
        _SM4_SBOX[(a >> 24) & 0xFF] << 24
        | _SM4_SBOX[(a >> 16) & 0xFF] << 16
        | _SM4_SBOX[(a >> 8) & 0xFF] << 8
        | _SM4_SBOX[a & 0xFF]
    )


def _sm4_l(b: int) -> int:
    return b ^ _rotl(b, 2) ^ _rotl(b, 10) ^ _rotl(b, 18) ^ _rotl(b, 24)


def _sm4_l_prime(b: int) -> int:
    return b ^ _rotl(b, 13) ^ _rotl(b, 23)


def _sm4_t(x: int) -> int:
    return _sm4_l(_sm4_tau(x))


def _sm4_t_prime(x: int) -> int:
    return _sm4_l_prime(_sm4_tau(x))


def _sm4_key_expand(key: bytes) -> list[int]:
    if len(key) != 16:
        raise ValueError("SM4 key must be 16 bytes")
    MK = struct.unpack(">4I", key)
    K = [MK[i] ^ _SM4_FK[i] for i in range(4)]
    rk = []
    for i in range(32):
        K.append(K[i] ^ _sm4_t_prime(K[i + 1] ^ K[i + 2] ^ K[i + 3] ^ _SM4_CK[i]))
        rk.append(K[i + 4])
    return rk


def _sm4_crypt_block(rk: list[int], block: bytes) -> bytes:
    X = list(struct.unpack(">4I", block))
    for i in range(32):
        X.append(X[i] ^ _sm4_t(X[i + 1] ^ X[i + 2] ^ X[i + 3] ^ rk[i]))
    return struct.pack(">4I", X[35], X[34], X[33], X[32])


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad] * pad)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad] * pad):
        raise ValueError("Invalid PKCS7 padding")
    return data[:-pad]


def sm4_encrypt(plaintext: Union[bytes, str], key: bytes, iv: bytes | None = None) -> bytes:
    """SM4-CBC encrypt with PKCS7 padding. Returns iv||ciphertext.

    If ``iv`` is None, generates a random one and prepends it. The returned
    blob is thus fully self-contained: ``sm4_decrypt(blob, key)`` works.
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    if len(key) != 16:
        raise ValueError("SM4 key must be 16 bytes")
    if iv is None:
        iv = os.urandom(16)
    elif len(iv) != 16:
        raise ValueError("SM4 IV must be 16 bytes")

    rk = _sm4_key_expand(key)
    data = _pkcs7_pad(plaintext)
    prev = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        block = bytes(b ^ p for b, p in zip(data[i:i + 16], prev))
        cipher = _sm4_crypt_block(rk, block)
        out.extend(cipher)
        prev = cipher
    return iv + bytes(out)


def sm4_decrypt(blob: bytes, key: bytes) -> bytes:
    """Reverse ``sm4_encrypt``. Expects iv||ciphertext."""
    if len(key) != 16:
        raise ValueError("SM4 key must be 16 bytes")
    if len(blob) < 32 or (len(blob) - 16) % 16 != 0:
        raise ValueError("Invalid SM4 blob")
    iv = blob[:16]
    ct = blob[16:]
    rk = _sm4_key_expand(key)
    rk_inv = list(reversed(rk))
    prev = iv
    out = bytearray()
    for i in range(0, len(ct), 16):
        cipher = ct[i:i + 16]
        plain = _sm4_crypt_block(rk_inv, cipher)
        out.extend(b ^ p for b, p in zip(plain, prev))
        prev = cipher
    return _pkcs7_unpad(bytes(out))


# ============================================================
# High-level helpers used by audit / log encryption
# ============================================================


def sm3_chain(previous_hash: bytes, payload: Union[bytes, str]) -> bytes:
    """Hash-chain link: H_n = SM3(H_{n-1} || payload). Used for tamper-evident logs."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return sm3_hash(previous_hash + payload)


def sm4_encrypt_str(plaintext: str, key: bytes) -> str:
    """Return hex-encoded ciphertext blob (iv||ct)."""
    return sm4_encrypt(plaintext, key).hex()


def sm4_decrypt_str(hex_blob: str, key: bytes) -> str:
    return sm4_decrypt(bytes.fromhex(hex_blob), key).decode("utf-8")
