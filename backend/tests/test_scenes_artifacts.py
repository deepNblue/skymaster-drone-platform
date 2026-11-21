"""v2.1 T1.3 · scenes_artifacts pure-function tests.

Real endpoints require FastAPI/DB fixtures (not part of this test file);
we test the pure helpers that do the heavy lifting:

* ``_rfc6266_disposition`` — Unicode-safe download filename header
* ``_guess_content_type``  — special-cases ``.ply`` / ``.splat``
* ``_filter_artifacts``    — separates trained artifacts from source data
* ``_asset_to_artifact``   — DB row → API DTO
"""
from __future__ import annotations

import urllib.parse
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.api.v1 import scenes_artifacts as sa


def test_disposition_ascii_only():
    v = sa._rfc6266_disposition("scene.ply")
    assert 'filename="scene.ply"' in v
    assert "filename*=UTF-8''scene.ply" in v


def test_disposition_unicode_is_percent_encoded():
    v = sa._rfc6266_disposition("场景1.ply")
    # ASCII fallback should not contain raw CJK
    assert "场景" not in v.split(";")[1]  # ascii fallback part
    # RFC 5987 part must percent-encode CJK
    assert urllib.parse.quote("场景1.ply", safe="") in v


def test_disposition_strips_path_separators():
    v = sa._rfc6266_disposition("../../etc/passwd")
    assert "/" not in v
    assert "\\" not in v
    # dots are fine (embedded in filename)
    assert "etc_passwd" in v


def test_disposition_strips_crlf():
    v = sa._rfc6266_disposition("a\r\nb.ply")
    assert "\r" not in v
    assert "\n" not in v


def test_content_type_ply_splat_are_octet_stream():
    assert sa._guess_content_type("model.ply") == "application/octet-stream"
    assert sa._guess_content_type("scene.splat") == "application/octet-stream"
    assert sa._guess_content_type("SCENE.PLY") == "application/octet-stream"


def test_content_type_zip():
    assert sa._guess_content_type("bundle.zip") == "application/zip"


def test_content_type_json_falls_through_to_mimetypes():
    v = sa._guess_content_type("manifest.json")
    assert v in ("application/json", "application/octet-stream")


def test_content_type_unknown_defaults_to_octet_stream():
    assert sa._guess_content_type("weird.xyz42") == "application/octet-stream"


def test_download_url_format():
    sid = uuid4()
    aid = uuid4()
    u = sa._download_url(sid, aid)
    assert u == f"/api/v1/scenes/{sid}/assets/{aid}/download"


def _fake_asset(kind: str, filename: str = "x.ply"):
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        filename=filename,
        size_bytes=1234,
        sha256_hex="a" * 64,
        storage_path="/tmp/x",
    )


def test_filter_artifacts_keeps_only_output_kinds():
    assets = [
        _fake_asset("source_image"),
        _fake_asset("source_video"),
        _fake_asset("gsplat_ply"),
        _fake_asset("gsplat_ckpt"),
        _fake_asset("colmap_sparse"),
        _fake_asset("log"),
        _fake_asset("preview_thumb"),
    ]
    kept = sa._filter_artifacts(assets)
    kept_kinds = {a.kind for a in kept}
    assert kept_kinds == {"gsplat_ply", "gsplat_ckpt", "colmap_sparse", "preview_thumb"}


def test_filter_artifacts_empty_list():
    assert sa._filter_artifacts([]) == []


def test_asset_to_artifact_carries_download_url():
    sid = uuid4()
    a = _fake_asset("gsplat_ply", "scene-final.ply")
    out = sa._asset_to_artifact(sid, a)
    assert out.kind == "gsplat_ply"
    assert out.filename == "scene-final.ply"
    assert out.size_bytes == 1234
    assert out.download_url == f"/api/v1/scenes/{sid}/assets/{a.id}/download"


def test_artifact_kinds_are_subset_of_scene_asset_kinds():
    from app.models.scene import SCENE_ASSET_KINDS

    assert set(sa.ARTIFACT_KINDS).issubset(set(SCENE_ASSET_KINDS))


def test_disposition_preserves_dot_extensions():
    v = sa._rfc6266_disposition("final.model.v2.ply")
    assert "final.model.v2.ply" in v


def test_disposition_null_byte_rejected_via_sanitize():
    v = sa._rfc6266_disposition("bad\x00file.ply")
    # We don't reject; we sanitize \x00 into _ implicitly via quote+ascii?
    # Actually null byte survives ascii encode? Verify no raw \x00 in header.
    assert "\x00" not in v
