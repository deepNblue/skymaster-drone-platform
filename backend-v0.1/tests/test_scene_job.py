"""v2.1 T2.3 · scene_job durable queue tests."""
from __future__ import annotations

import asyncio
from uuid import uuid4, UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.services import scene_job as jobsvc
from app.models.scene import Scene
from app.models.scene_job import SceneJob, MAX_ATTEMPTS


@pytest_asyncio.fixture
async def session(client):  # noqa: ARG001
    from app.db import engine
    Sess = async_sessionmaker(engine, expire_on_commit=False)
    async with Sess() as s:
        yield s


async def _make_scene(session, org_id=None) -> Scene:
    scene = Scene(
        id=uuid4(),
        org_id=org_id or uuid4(),
        name=f"S-{uuid4().hex[:6]}",
        status="ingested",
    )
    session.add(scene)
    await session.commit()
    return scene


# ---------- enqueue -------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_happy_path(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap", priority=5,
    ))
    await session.commit()
    assert job.status == "queued"
    assert job.attempts == 0
    assert job.priority == 5


@pytest.mark.asyncio
async def test_enqueue_unknown_kind_rejected(session):
    scene = await _make_scene(session)
    with pytest.raises(jobsvc.JobError):
        await jobsvc.enqueue(session, jobsvc.EnqueueParams(
            scene_id=scene.id, kind="bogus",
        ))


@pytest.mark.asyncio
async def test_enqueue_dedupes_active_kind(session):
    scene = await _make_scene(session)
    await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="training",
    ))
    await session.commit()
    with pytest.raises(jobsvc.JobError):
        await jobsvc.enqueue(session, jobsvc.EnqueueParams(
            scene_id=scene.id, kind="training",
        ))


@pytest.mark.asyncio
async def test_enqueue_allows_different_kinds(session):
    scene = await _make_scene(session)
    await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="training",
    ))
    await session.commit()


# ---------- claim ---------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_returns_none_when_empty(session):
    job = await jobsvc.claim_next(session, worker_id="w1")
    assert job is None


@pytest.mark.asyncio
async def test_claim_by_priority_then_age(session):
    scene = await _make_scene(session)
    low = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap", priority=0,
    ))
    await session.commit()

    scene2 = await _make_scene(session)
    high = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene2.id, kind="colmap", priority=10,
    ))
    await session.commit()

    got = await jobsvc.claim_next(session, worker_id="w1", kinds=["colmap"])
    await session.commit()
    assert got is not None
    assert got.id == high.id
    assert got.status == "leased"
    assert got.worker_id == "w1"
    assert got.attempts == 1


@pytest.mark.asyncio
async def test_claim_filters_by_kind(session):
    scene = await _make_scene(session)
    training_job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="training",
    ))
    await session.commit()
    # Claim workers looking for colmap only should skip this
    got = await jobsvc.claim_next(session, "w1", kinds=["colmap"])
    assert got is None
    got = await jobsvc.claim_next(session, "w1", kinds=["training"])
    await session.commit()
    assert got.id == training_job.id


@pytest.mark.asyncio
async def test_claim_bumps_attempts_across_claims(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()

    got = await jobsvc.claim_next(session, "w1")
    await session.commit()
    assert got.attempts == 1
    # Simulate worker failure that requeues job
    await jobsvc.fail(session, got.id, "w1", error="worker crashed")
    await session.commit()
    got2 = await jobsvc.claim_next(session, "w2")
    await session.commit()
    assert got2 is not None
    assert got2.id == job.id
    assert got2.attempts == 2


# ---------- heartbeat -----------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_and_promotes_to_running(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()
    await jobsvc.claim_next(session, "w1")
    await session.commit()

    old_exp = job.lease_expires_at
    await asyncio.sleep(0.01)
    hb = await jobsvc.heartbeat(session, job.id, "w1", lease_seconds=600)
    await session.commit()
    assert hb.status == "running"
    assert hb.lease_expires_at > (old_exp or hb.leased_at)


@pytest.mark.asyncio
async def test_heartbeat_wrong_worker_rejected(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()
    await jobsvc.claim_next(session, "w1")
    await session.commit()
    with pytest.raises(jobsvc.JobError):
        await jobsvc.heartbeat(session, job.id, "w2")


# ---------- complete / fail / cancel --------------------------------------


@pytest.mark.asyncio
async def test_complete_records_result_metrics(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="training",
    ))
    await session.commit()
    await jobsvc.claim_next(session, "w1", kinds=["training"])
    await session.commit()

    done = await jobsvc.complete(
        session, job.id, "w1",
        result=jobsvc.CompleteParams(n_gaussians=1_000_000, psnr=28.5),
    )
    await session.commit()
    assert done.status == "succeeded"
    assert done.result_n_gaussians == 1_000_000
    assert done.result_psnr == 28.5
    assert done.finished_at is not None


@pytest.mark.asyncio
async def test_complete_wrong_worker_rejected(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="training",
    ))
    await session.commit()
    await jobsvc.claim_next(session, "w1", kinds=["training"])
    await session.commit()
    with pytest.raises(jobsvc.JobError):
        await jobsvc.complete(session, job.id, "wRogue")


@pytest.mark.asyncio
async def test_fail_requeues_until_max_attempts(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()

    for i in range(MAX_ATTEMPTS - 1):
        await jobsvc.claim_next(session, f"w{i}")
        await session.commit()
        await jobsvc.fail(session, job.id, f"w{i}", error=f"fail {i}")
        await session.commit()

    fresh = (await session.execute(select(SceneJob).where(SceneJob.id == job.id))).scalar_one()
    assert fresh.status == "queued"
    assert fresh.attempts == MAX_ATTEMPTS - 1

    # Last attempt → dead
    await jobsvc.claim_next(session, "wFinal")
    await session.commit()
    await jobsvc.fail(session, job.id, "wFinal", error="terminal")
    await session.commit()

    fresh = (await session.execute(select(SceneJob).where(SceneJob.id == job.id))).scalar_one()
    assert fresh.status == "dead"
    assert fresh.attempts == MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_cancel_active_job(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()
    canceled = await jobsvc.cancel(session, job.id)
    await session.commit()
    assert canceled.status == "canceled"


@pytest.mark.asyncio
async def test_cancel_terminal_job_rejected(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()
    await jobsvc.cancel(session, job.id)
    await session.commit()
    with pytest.raises(jobsvc.JobError):
        await jobsvc.cancel(session, job.id)


# ---------- lease expiry / reclaim ---------------------------------------


@pytest.mark.asyncio
async def test_reclaim_stale_puts_expired_lease_back_to_queued(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()

    got = await jobsvc.claim_next(session, "w1")
    await session.commit()
    assert got.status == "leased"

    # Simulate expired lease by rewriting lease_expires_at to the past
    from datetime import datetime, timezone, timedelta
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    await session.execute(
        update(SceneJob).where(SceneJob.id == job.id).values(lease_expires_at=past)
    )
    await session.commit()

    n = await jobsvc.reclaim_stale(session)
    await session.commit()
    assert n == 1

    fresh = (await session.execute(select(SceneJob).where(SceneJob.id == job.id))).scalar_one()
    assert fresh.status == "queued"
    assert fresh.worker_id is None
    assert fresh.lease_expires_at is None
    assert "lease expired" in (fresh.last_error or "")


@pytest.mark.asyncio
async def test_expired_lease_at_max_attempts_dies(session):
    scene = await _make_scene(session)
    job = await jobsvc.enqueue(session, jobsvc.EnqueueParams(
        scene_id=scene.id, kind="colmap",
    ))
    await session.commit()
    # Fake the job already exhausted its attempts
    await session.execute(
        update(SceneJob).where(SceneJob.id == job.id).values(attempts=MAX_ATTEMPTS)
    )
    await session.commit()

    got = await jobsvc.claim_next(session, "w1")
    await session.commit()
    from datetime import datetime, timezone, timedelta
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    await session.execute(
        update(SceneJob).where(SceneJob.id == job.id).values(lease_expires_at=past)
    )
    await session.commit()

    await jobsvc.reclaim_stale(session)
    await session.commit()
    fresh = (await session.execute(select(SceneJob).where(SceneJob.id == job.id))).scalar_one()
    assert fresh.status == "dead"


# ---------- stats ---------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_stats(session):
    scene = await _make_scene(session)
    await jobsvc.enqueue(session, jobsvc.EnqueueParams(scene_id=scene.id, kind="colmap"))
    scene2 = await _make_scene(session)
    await jobsvc.enqueue(session, jobsvc.EnqueueParams(scene_id=scene2.id, kind="training"))
    await session.commit()

    stats = await jobsvc.queue_stats(session)
    assert stats["total"] == 2
    assert stats["by_kind"]["colmap"]["queued"] == 1
    assert stats["by_kind"]["training"]["queued"] == 1
