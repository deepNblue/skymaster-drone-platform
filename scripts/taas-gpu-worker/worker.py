#!/usr/bin/env python3
"""
TaaS GPU Node Worker — SkyMaster v2.3
Runs on your GPU machine, polls for jobs, executes training, reports metrics.

Usage:
  export SKYMASTER_API_URL=https://your-skymaster-server.com/api/v1
  export SKYMASTER_NODE_ID=your-node-uuid
  export SKYMASTER_API_KEY=your-node-api-key
  python worker.py
"""
import os
import sys
import time
import json
import subprocess
from typing import Optional, Dict, Any
import requests

# Configuration from environment
API_URL = os.environ.get("SKYMASTER_API_URL", "http://localhost:8000/api/v1")
NODE_ID = os.environ.get("SKYMASTER_NODE_ID")
API_KEY = os.environ.get("SKYMASTER_API_KEY")

if not NODE_ID or not API_KEY:
    print("ERROR: SKYMASTER_NODE_ID and SKYMASTER_API_KEY must be set")
    sys.exit(1)


def get_vram_used() -> int:
    """Get current used VRAM in bytes using nvidia-smi."""
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            encoding="utf-8",
        )
        # For single GPU, take first line
        mb_used = int(output.strip().split()[0])
        return mb_used * 1024 * 1024
    except Exception as e:
        print(f"Warning: failed to get VRAM: {e}")
        return 0


def heartbeat() -> bool:
    """Send heartbeat with current VRAM usage."""
    url = f"{API_URL}/taas-node/{NODE_ID}/heartbeat"
    used = get_vram_used()
    try:
        resp = requests.post(url, params={"access_key": NODE_ID}, json={
            "used_vram_bytes": used,
        })
        return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception as e:
        print(f"Heartbeat failed: {e}")
        return False


def claim_next() -> Optional[Dict[str, Any]]:
    """Claim next scheduled job."""
    url = f"{API_URL}/taas-node/{NODE_ID}/claim-next"
    try:
        resp = requests.get(url, params={"access_key": NODE_ID})
        data = resp.json()
        if not data.get("ok", False) or not data.get("job_id"):
            return None
        # Get full job info
        job_resp = requests.get(f"{API_URL}/taas/jobs/{data['job_id']}", params={"access_key": NODE_ID})
        return job_resp.json()
    except Exception as e:
        print(f"claim-next failed: {e}")
        return None


def report_metric(job_id: str, step: int, epoch: Optional[int], loss: Optional[float], accuracy: Optional[float] = None) -> bool:
    """Report training metric to server."""
    url = f"{API_URL}/taas-node/jobs/{job_id}/metrics"
    body = {
        "step": step,
        "epoch": epoch,
        "loss": loss,
        "accuracy": accuracy,
    }
    try:
        resp = requests.post(url, params={"access_key": NODE_ID}, json=body)
        return resp.status_code == 201
    except Exception as e:
        print(f"report-metric failed: {e}")
        return False


def report_finished(job_id: str, success: bool, output_uri: Optional[str], error: Optional[str], gpu_hours: float, cost_cents: int) -> bool:
    """Report job finished."""
    url = f"{API_URL}/taas-node/jobs/{job_id}/finished"
    body = {
        "success": success,
        "output_model_uri": output_uri,
        "error_message": error,
        "gpu_hours_used": gpu_hours,
        "cost_cents": cost_cents,
    }
    try:
        resp = requests.post(url, params={"access_key": NODE_ID}, json=body)
        return resp.status_code == 200
    except Exception as e:
        print(f"report-finished failed: {e}")
        return False


def run_training(job: Dict[str, Any]) -> None:
    """
    Actual training:
    1. Download dataset and base model
    2. Run training script, periodically report metrics
    3. Upload final model to storage
    4. Report completion
    """
    job_id = job["id"]
    print(f"Starting training job {job_id}: {job['name']}")

    start_time = time.time()
    price_per_hour_cents = 1000  # $0.10 / hour, adjust for your pricing

    # TODO: implement actual training logic for your model type
    # Below is a skeleton that you can adapt:

    try:
        # 1. Download dataset from job['dataset']['storageUri']
        # 2. Load base model from job['baseModelUri'] or marketplace
        # 3. Initialize training loop

        # Example placeholder training loop:
        # for epoch in range(job['numEpochs']):
        #   for i, batch in enumerate(dataloader):
        #       loss = model.train_batch(batch)
        #       if i % log_steps == 0:
        #           report_metric(job_id, step, epoch + 1, float(loss))
        #           heartbeat()  # update vram usage

        # For demonstration: just sleep and report fake metrics
        steps = 10
        for step in range(1, steps + 1):
            time.sleep(10)
            fake_loss = 1.0 / step
            report_metric(job_id, step, 1, fake_loss)
            heartbeat()

        # 4. Save and upload final model to output_uri
        output_uri = f"minio://models/taas/{job_id}/final.pth"
        success = True
        error = None

    except Exception as e:
        success = False
        error = str(e)
        output_uri = None
        print(f"Training failed: {e}")

    elapsed_hours = (time.time() - start_time) / 3600
    cost_cents = int(elapsed_hours * price_per_hour_cents)
    report_finished(job_id, success, output_uri, error, elapsed_hours, cost_cents)
    print(f"Job {job_id} finished, elapsed {elapsed_hours:.2f}h, cost {cost_cents / 100:.2f}")


def main():
    print(f"Starting TaaS GPU worker, node {NODE_ID}")
    print(f"API URL: {API_URL}")

    while True:
        # Send heartbeat
        ok = heartbeat()
        if not ok:
            time.sleep(10)
            continue

        # Claim next job
        job = claim_next()
        if job is None:
            # No job, wait
            time.sleep(30)
            continue

        # Run the job
        run_training(job)


if __name__ == "__main__":
    main()
