"""Object storage abstraction — v2.1 T1.1.

Pluggable backend for scene assets (source images/videos, COLMAP outputs,
Gaussian splatting checkpoints). Local FS for dev; S3/MinIO/OSS for prod.

Design goals
------------

1. **Content-addressed storage (CAS)** — files are keyed by ``sha256_hex``
   so identical uploads dedup automatically across scenes/orgs.
2. **Chunked assembly** — chunks are staged under
   ``{root}/staging/{upload_id}/{chunk_idx}`` then atomically concatenated
   into ``{root}/cas/{sha[:2]}/{sha[2:]}`` on completion.
3. **No secrets in path** — upload_id is a UUID; the CAS key is a strong
   hash. Directory traversal is blocked by rejecting any path component
   containing ``..`` or ``/``.
4. **Backend-swappable** — the ``StorageBackend`` protocol is the only
   surface the rest of the app touches; S3Backend is trivial to add.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StorageError(Exception):
    pass


class StorageIntegrityError(StorageError):
    """Actual sha256 of assembled file didn't match the client-declared hash."""


class StorageChunkMissing(StorageError):
    pass


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@dataclass
class ObjectRef:
    """A stored object — content-addressed."""

    sha256_hex: str
    size_bytes: int
    # Backend-specific pointer (fs path, s3 key, etc.). Callers don't parse it.
    storage_path: str

    def cas_key(self) -> str:
        return self.sha256_hex


class StorageBackend(ABC):
    @abstractmethod
    def stage_chunk(self, upload_id: str, chunk_idx: int, data: bytes) -> None: ...

    @abstractmethod
    def list_chunks(self, upload_id: str) -> list[int]: ...

    @abstractmethod
    def assemble(
        self, upload_id: str, expected_sha256: str, total_chunks: int
    ) -> ObjectRef: ...

    @abstractmethod
    def open_read(self, ref: ObjectRef) -> BinaryIO: ...

    @abstractmethod
    def size(self, ref: ObjectRef) -> int: ...

    @abstractmethod
    def delete_staging(self, upload_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


def _safe_component(s: str) -> str:
    """Reject any input that could break out of the storage root."""
    if not s or "/" in s or ".." in s or "\\" in s or "\x00" in s:
        raise StorageError(f"invalid path component: {s!r}")
    return s


class LocalFSBackend(StorageBackend):
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        (self.root / "staging").mkdir(parents=True, exist_ok=True)
        (self.root / "cas").mkdir(parents=True, exist_ok=True)

    # --- staging ---------------------------------------------------------

    def _staging_dir(self, upload_id: str) -> Path:
        upload_id = _safe_component(upload_id)
        p = self.root / "staging" / upload_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def stage_chunk(self, upload_id: str, chunk_idx: int, data: bytes) -> None:
        if chunk_idx < 0 or chunk_idx > 100_000:
            raise StorageError(f"chunk_idx out of range: {chunk_idx}")
        p = self._staging_dir(upload_id) / f"{chunk_idx:06d}.chunk"
        tmp = p.with_suffix(".chunk.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def list_chunks(self, upload_id: str) -> list[int]:
        d = self._staging_dir(upload_id)
        idxs = []
        for f in d.iterdir():
            if f.suffix == ".chunk":
                try:
                    idxs.append(int(f.stem))
                except ValueError:
                    continue
        return sorted(idxs)

    # --- CAS assembly ----------------------------------------------------

    def _cas_path(self, sha: str) -> Path:
        if len(sha) != 64:
            raise StorageError(f"invalid sha256 hex length: {len(sha)}")
        # subdir shard to keep dir sizes sane
        return self.root / "cas" / sha[:2] / sha[2:]

    def assemble(
        self, upload_id: str, expected_sha256: str, total_chunks: int
    ) -> ObjectRef:
        chunks = self.list_chunks(upload_id)
        expected = list(range(total_chunks))
        if chunks != expected:
            missing = sorted(set(expected) - set(chunks))
            raise StorageChunkMissing(f"missing chunks: {missing[:10]}")

        cas_path = self._cas_path(expected_sha256)
        cas_path.parent.mkdir(parents=True, exist_ok=True)

        # If dedup — same file already on disk — return the existing ref
        if cas_path.exists():
            # Verify integrity of existing file (paranoid mode).
            actual = _sha256_file(cas_path)
            if actual != expected_sha256:
                raise StorageIntegrityError(
                    f"CAS entry corrupt: expected {expected_sha256}, got {actual}"
                )
            self.delete_staging(upload_id)
            return ObjectRef(
                sha256_hex=expected_sha256,
                size_bytes=cas_path.stat().st_size,
                storage_path=str(cas_path),
            )

        # Concatenate chunks → CAS path, compute sha256 along the way.
        tmp = cas_path.with_suffix(".tmp")
        h = hashlib.sha256()
        size = 0
        with tmp.open("wb") as out:
            for idx in chunks:
                cpath = self._staging_dir(upload_id) / f"{idx:06d}.chunk"
                with cpath.open("rb") as src:
                    while True:
                        buf = src.read(1 << 20)
                        if not buf:
                            break
                        h.update(buf)
                        out.write(buf)
                        size += len(buf)

        actual_sha = h.hexdigest()
        if actual_sha != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise StorageIntegrityError(
                f"sha256 mismatch: expected {expected_sha256}, got {actual_sha}"
            )

        os.replace(tmp, cas_path)
        self.delete_staging(upload_id)
        return ObjectRef(
            sha256_hex=expected_sha256, size_bytes=size, storage_path=str(cas_path)
        )

    # --- misc ------------------------------------------------------------

    def open_read(self, ref: ObjectRef) -> BinaryIO:
        return open(ref.storage_path, "rb")

    def size(self, ref: ObjectRef) -> int:
        return Path(ref.storage_path).stat().st_size

    def delete_staging(self, upload_id: str) -> None:
        d = self._staging_dir(upload_id)
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            buf = f.read(1 << 20)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Default singleton (env-configurable)
# ---------------------------------------------------------------------------


def _default_root() -> Path:
    return Path(os.environ.get("SKYMASTER_STORAGE_ROOT", "/tmp/skymaster-storage")).resolve()


_backend: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        _backend = LocalFSBackend(_default_root())
    return _backend


def set_storage(b: StorageBackend) -> None:  # test/DI hook
    global _backend
    _backend = b
