"""TaaS Scheduler — assigns queued jobs to available GPU nodes.

v2.3 E6.1 — basic scheduling logic:
1. Find queued jobs that are ready to run
2. Select GPU node with:
   - enabled
   - heartbeat recent (< 5 minutes)
   - enough free VRAM for requested size
   - least loaded (minimum used VRAM)
3. Mark job as scheduled + assign node
4. Node side pulls job via long-polling / webhook
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.taas import GPUNode, FineTuneJob


class Scheduler:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def schedule_one(
        self,
        db: AsyncSession,
    ) -> bool:
        """Try to schedule one queued job. Return True if scheduled."""
        # Find earliest queued job
        queued_query = (
            select(FineTuneJob)
            .where(FineTuneJob.state == "queued")
            .order_by(FineTuneJob.created_at.asc())
            .limit(1)
        )
        result = await db.execute(queued_query)
        job = result.scalar_one_or_none()
        if job is None:
            return False  # no queued jobs

        # Calculate requested VRAM (rough estimate)
        # If job didn't specify, estimate based on hyperparams
        requested_bytes = job.requested_vram_bytes
        if requested_bytes is None:
            # Very rough heuristic: base model + batch + gradients
            requested_bytes = self._estimate_vram(job)
            job.requested_vram_bytes = requested_bytes
            await db.commit()

        # Find available nodes
        now = datetime.utcnow()
        node_query = select(GPUNode).where(
            GPUNode.enabled == True,
            GPUNode.last_heartbeat_at != None,
        )
        nodes_result = await db.execute(node_query)
        nodes = nodes_result.scalars().all()

        candidates: list[tuple[GPUNode, int]] = []
        for node in nodes:
            # Check heartbeat — node must have checked in recently
            if node.last_heartbeat_at is None:
                continue
            age = (now - node.last_heartbeat_at).total_seconds()
            if age > 300:  # 5 minutes
                continue
            free_bytes = node.total_vram_bytes - node.used_vram_bytes
            if free_bytes >= requested_bytes:
                candidates.append((node, free_bytes))

        if not candidates:
            # No available node — leave queued for next scheduling round
            return False

        # Pick candidate with most free VRAM (least loaded)
        candidates.sort(key=lambda x: -x[1])
        best_node = candidates[0][0]

        # Assign job to node and mark as scheduled
        job.state = "scheduled"
        job.scheduled_node_id = best_node.id
        await db.commit()

        # TODO: send webhook to node to start pulling job
        # For MVP: node long-polls / polls for new jobs

        return True

    def _estimate_vram(self, job: FineTuneJob) -> int:
        """Very rough VRAM estimate in bytes."""
        base = 2 * 1024 ** 3  # 2 GB base
        if job.lora_rank is not None:
            # LoRA fine-tune needs much less VRAM
            # typical 7B model LoRA ~ 4-6 GB total
            return int(base + 2 * 1024 ** 3)  # 4 GB
        # Full fine-tune needs more
        # add gradient + optimizer states
        return int(base * 4)  # 8 GB default

    async def run_scheduling_loop(
        self,
        get_db: callable,
        interval_seconds: float = 10.0,
    ) -> None:
        """Background loop that tries to schedule jobs every N seconds."""
        self._running = True
        while self._running:
            try:
                async for db in get_db():
                    scheduled = await self.schedule_one(db)
                    if scheduled:
                        # Try again immediately for next job
                        continue
                    # No more schedulable jobs — wait
                    break
            except Exception as e:
                # Log but keep running
                print(f"[TaaS Scheduler] Error in scheduling loop: {e}")
            await asyncio.sleep(interval_seconds)

    def start(
        self,
        get_db: callable,
        interval_seconds: float = 10.0,
    ) -> None:
        """Start background scheduling loop."""
        if self._running:
            return
        self._task = asyncio.create_task(
            self.run_scheduling_loop(get_db, interval_seconds)
        )

    def stop(self) -> None:
        """Stop background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None


# Global singleton scheduler
scheduler = Scheduler()


async def assign_heartbeat(
    node_id: UUID,
    used_vram_bytes: int,
    db: AsyncSession,
) -> bool:
    """Update node heartbeat and used VRAM. Called by node agent."""
    node = (
        await db.execute(select(GPUNode).where(GPUNode.id == node_id))
    ).scalar_one_or_none()
    if node is None:
        return False
    node.last_heartbeat_at = datetime.utcnow()
    node.used_vram_bytes = used_vram_bytes
    await db.commit()
    return True
