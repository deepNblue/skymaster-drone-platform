"""Sanity import test — verifies every backend module loads cleanly.

If any module has a syntax error, missing dependency, or import-time
side-effect that fails without infra, this test will surface it.
"""
from __future__ import annotations

import importlib


CORE_MODULES = [
    "app.main",
    "app.db",
    "app.config",
    "app.deps",
]

MODEL_MODULES = [
    "app.models",
    "app.models.audit_log",
    "app.models.drone",
    "app.models.flight_log",
    "app.models.media_asset",
    "app.models.mission",
    "app.models.organization",
    "app.models.user",
]

API_V1_MODULES = [
    "app.api",
    "app.api.v1",
    "app.api.v1.router",
    "app.api.v1.auth",
    "app.api.v1.drones",
    "app.api.v1.health",
    "app.api.v1.missions",
    "app.api.v1.streams",
    "app.api.v1.websocket",
]


def test_core_modules_import() -> None:
    for name in CORE_MODULES:
        assert importlib.import_module(name) is not None, name


def test_model_modules_import() -> None:
    for name in MODEL_MODULES:
        assert importlib.import_module(name) is not None, name


def test_api_v1_modules_import() -> None:
    for name in API_V1_MODULES:
        assert importlib.import_module(name) is not None, name
