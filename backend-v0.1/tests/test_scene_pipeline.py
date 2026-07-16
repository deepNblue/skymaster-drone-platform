"""3DGS scene pipeline state-machine tests (v2.1 T1)."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services import scene_pipeline as sp
from app.services.scene_pipeline import (
    ExecResult, Executor, InvalidTransition,
    can_transition, get_executor, set_executor,
)


class _FakeScene:
    """Minimal duck-typed Scene for state machine tests (no DB)."""

    def __init__(self, status="draft"):
        self.id = uuid4()
        self.status = status
        self.error_msg = None
        self.n_points = None
        self.n_gaussians = None
        self.psnr_train = None


class _FakeSession:
    async def flush(self):
        return None

    async def commit(self):
        return None


class _FailExecutor(Executor):
    async def run_colmap(self, scene_id):  # noqa: ARG002
        return ExecResult(ok=False, error="fake colmap boom")

    async def run_training(self, scene_id):  # noqa: ARG002
        return ExecResult(ok=False, error="fake training boom")


class _SuccessExecutor(Executor):
    async def run_colmap(self, scene_id):  # noqa: ARG002
        return ExecResult(ok=True, n_points=9999)

    async def run_training(self, scene_id):  # noqa: ARG002
        return ExecResult(ok=True, n_gaussians=555_555, psnr_train=31.2)


# ---------------------------------------------------------------------------


def test_legal_transitions_happy_path():
    seq = ["draft", "ingesting", "ingested", "colmap", "colmap_done", "training", "ready"]
    for a, b in zip(seq[:-1], seq[1:]):
        assert can_transition(a, b), f"{a}→{b} must be legal"


def test_terminal_states_reject_further_transitions():
    # archived is fully terminal
    for target in ("draft", "training", "ready", "failed"):
        assert not can_transition("archived", target), f"archived→{target}"
    # ready only goes to archived
    assert can_transition("ready", "archived")
    for target in ("draft", "colmap", "training", "ingested"):
        assert not can_transition("ready", target)


def test_illegal_transitions_are_blocked():
    # Cannot skip stages
    assert not can_transition("draft", "colmap")
    assert not can_transition("draft", "ready")
    assert not can_transition("ingested", "training")
    assert not can_transition("colmap_done", "ready")


def test_failed_can_reset_or_archive():
    assert can_transition("failed", "draft")
    assert can_transition("failed", "archived")
    assert not can_transition("failed", "colmap")


def test_transition_rejects_illegal_move():
    scene = _FakeScene(status="draft")
    db = _FakeSession()
    with pytest.raises(InvalidTransition):
        asyncio.run(sp.transition(db, scene, "ready"))
    # State unchanged
    assert scene.status == "draft"


def test_transition_clears_error_on_recovery():
    scene = _FakeScene(status="failed")
    scene.error_msg = "old error"
    db = _FakeSession()
    asyncio.run(sp.transition(db, scene, "draft"))
    assert scene.status == "draft"
    assert scene.error_msg is None


def test_transition_records_error_on_failed():
    scene = _FakeScene(status="colmap")
    db = _FakeSession()
    asyncio.run(sp.transition(db, scene, "failed", error_msg="OOM in SfM"))
    assert scene.status == "failed"
    assert "OOM" in scene.error_msg


def test_start_colmap_success_advances_and_records_metrics():
    prev = get_executor()
    try:
        set_executor(_SuccessExecutor())
        scene = _FakeScene(status="ingested")
        asyncio.run(sp.start_colmap(_FakeSession(), scene))
        assert scene.status == "colmap_done"
        assert scene.n_points == 9999
    finally:
        set_executor(prev)


def test_start_colmap_failure_transitions_to_failed():
    prev = get_executor()
    try:
        set_executor(_FailExecutor())
        scene = _FakeScene(status="ingested")
        asyncio.run(sp.start_colmap(_FakeSession(), scene))
        assert scene.status == "failed"
        assert "colmap boom" in scene.error_msg
    finally:
        set_executor(prev)


def test_start_training_success_records_gaussians_and_psnr():
    prev = get_executor()
    try:
        set_executor(_SuccessExecutor())
        scene = _FakeScene(status="colmap_done")
        asyncio.run(sp.start_training(_FakeSession(), scene))
        assert scene.status == "ready"
        assert scene.n_gaussians == 555_555
        assert scene.psnr_train == 31.2
    finally:
        set_executor(prev)


def test_start_training_from_wrong_state_raises():
    scene = _FakeScene(status="draft")
    with pytest.raises(InvalidTransition):
        asyncio.run(sp.start_training(_FakeSession(), scene))


def test_noop_executor_is_default_and_succeeds():
    ex = sp.NoOpExecutor()
    r1 = asyncio.run(ex.run_colmap(uuid4()))
    r2 = asyncio.run(ex.run_training(uuid4()))
    assert r1.ok and r1.n_points and r1.n_points > 0
    assert r2.ok and r2.n_gaussians and r2.psnr_train


def test_all_states_are_valid_enum():
    from app.models.scene import SCENE_STATUSES

    # every state used in transitions must be declared in the enum
    used = set()
    for s, dests in sp._LEGAL_TRANSITIONS.items():
        used.add(s)
        used.update(dests)
    assert used.issubset(set(SCENE_STATUSES)), used - set(SCENE_STATUSES)
