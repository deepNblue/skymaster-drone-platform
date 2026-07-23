"""v2.1 T1.1 · object_storage tests (chunked, CAS, dedup, integrity)."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app.services.object_storage import (
    LocalFSBackend, ObjectRef, StorageChunkMissing, StorageError,
    StorageIntegrityError, _sha256_file, _safe_component,
)


@pytest.fixture
def tmp_backend():
    d = tempfile.mkdtemp(prefix="skymaster-storage-test-")
    try:
        yield LocalFSBackend(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_safe_component_blocks_traversal():
    for bad in ["../", "a/b", "..", "a\\b", "a\x00b"]:
        with pytest.raises(StorageError):
            _safe_component(bad)
    assert _safe_component("safe123") == "safe123"


def test_stage_and_list_chunks(tmp_backend):
    uid = "u-abc123"
    tmp_backend.stage_chunk(uid, 0, b"hello ")
    tmp_backend.stage_chunk(uid, 1, b"world")
    tmp_backend.stage_chunk(uid, 3, b"gap")  # unordered on purpose
    idxs = tmp_backend.list_chunks(uid)
    assert idxs == [0, 1, 3]


def test_stage_chunk_rejects_out_of_range(tmp_backend):
    with pytest.raises(StorageError):
        tmp_backend.stage_chunk("u1", -1, b"x")
    with pytest.raises(StorageError):
        tmp_backend.stage_chunk("u1", 200_000, b"x")


def test_assemble_happy_path_two_chunks(tmp_backend):
    payload = b"the quick brown fox jumps over the lazy dog"
    tmp_backend.stage_chunk("uid1", 0, payload[:20])
    tmp_backend.stage_chunk("uid1", 1, payload[20:])
    ref = tmp_backend.assemble("uid1", _sha(payload), total_chunks=2)
    assert ref.sha256_hex == _sha(payload)
    assert ref.size_bytes == len(payload)
    assert Path(ref.storage_path).read_bytes() == payload
    # staging cleaned
    assert tmp_backend.list_chunks("uid1") == []


def test_assemble_missing_chunk_raises(tmp_backend):
    payload = b"abcdefg"
    tmp_backend.stage_chunk("uid2", 0, payload[:3])
    # chunk 1 absent
    with pytest.raises(StorageChunkMissing) as exc:
        tmp_backend.assemble("uid2", _sha(payload), total_chunks=2)
    assert "1" in str(exc.value)


def test_assemble_integrity_mismatch_raises(tmp_backend):
    real = b"real data"
    tmp_backend.stage_chunk("uid3", 0, real)
    wrong_sha = _sha(b"different data")
    with pytest.raises(StorageIntegrityError):
        tmp_backend.assemble("uid3", wrong_sha, total_chunks=1)
    # tmp file cleaned up
    cas = tmp_backend._cas_path(wrong_sha)
    tmp = cas.with_suffix(".tmp")
    assert not tmp.exists()


def test_assemble_dedup_returns_existing(tmp_backend):
    payload = b"same file content"
    sha = _sha(payload)
    tmp_backend.stage_chunk("first", 0, payload)
    ref1 = tmp_backend.assemble("first", sha, total_chunks=1)
    original_mtime = Path(ref1.storage_path).stat().st_mtime_ns
    # second upload of same content
    tmp_backend.stage_chunk("second", 0, payload)
    ref2 = tmp_backend.assemble("second", sha, total_chunks=1)
    assert ref2.storage_path == ref1.storage_path
    assert ref2.sha256_hex == sha
    # not rewritten
    assert Path(ref2.storage_path).stat().st_mtime_ns == original_mtime
    # staging of second cleaned
    assert tmp_backend.list_chunks("second") == []


def test_open_read_and_size(tmp_backend):
    payload = b"blob 42"
    tmp_backend.stage_chunk("uid4", 0, payload)
    ref = tmp_backend.assemble("uid4", _sha(payload), total_chunks=1)
    assert tmp_backend.size(ref) == len(payload)
    with tmp_backend.open_read(ref) as f:
        assert f.read() == payload


def test_delete_staging_is_idempotent(tmp_backend):
    tmp_backend.stage_chunk("uid5", 0, b"x")
    tmp_backend.delete_staging("uid5")
    tmp_backend.delete_staging("uid5")  # second call: no throw
    assert tmp_backend.list_chunks("uid5") == []


def test_assemble_detects_corrupted_cas_entry(tmp_backend):
    payload = b"pristine bytes"
    sha = _sha(payload)
    cas = tmp_backend._cas_path(sha)
    cas.parent.mkdir(parents=True, exist_ok=True)
    cas.write_bytes(b"corrupt bytes")  # sha mismatch on disk

    tmp_backend.stage_chunk("uid6", 0, payload)
    with pytest.raises(StorageIntegrityError):
        tmp_backend.assemble("uid6", sha, total_chunks=1)


def test_cas_path_rejects_bad_sha(tmp_backend):
    with pytest.raises(StorageError):
        tmp_backend._cas_path("tooshort")


def test_large_multipart_assembly(tmp_backend):
    # 5 chunks of 4KB each = 20KB
    parts = [os.urandom(4096) for _ in range(5)]
    full = b"".join(parts)
    for i, p in enumerate(parts):
        tmp_backend.stage_chunk("big1", i, p)
    ref = tmp_backend.assemble("big1", _sha(full), total_chunks=5)
    assert ref.size_bytes == len(full)
    assert _sha256_file(Path(ref.storage_path)) == _sha(full)
