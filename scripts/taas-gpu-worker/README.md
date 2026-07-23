# TaaS GPU Worker — SkyMaster v2.3

This is the reference GPU worker implementation for SkyMaster Training-as-a-Service.

## Quick Start

1. Get your node registered in SkyMaster backend:

   Admin calls API to create a GPU node:
   ```http
   POST /taas/gpu-nodes
   {
     "name": "my-rtx3090-node",
     "address": "hostname:port",
     "api_key": "<random-generated-key>",
     "gpu_model": "NVIDIA GeForce RTX 3090",
     "total_vram_bytes": 24 * 1024^3
   }
   ```

2. Set environment on your GPU machine:

   ```bash
   export SKYMASTER_API_URL=https://your-skymaster-server.com/api/v1
   export SKYMASTER_NODE_ID=<uuid-from-above>
   export SKYMASTER_API_KEY=<your-api-key>
   ```

3. Install dependencies:

   ```bash
   pip install requests
   # nvidia-smi must be available for VRAM reporting
   ```

4. Run:

   ```bash
   nohup python worker.py > worker.log 2>&1 &
   ```

Worker will:
- Send periodic heartbeat with current VRAM usage
- Poll for new scheduled jobs
- Run training and report metrics back to the server
- Report final success/failure

## How it works

```
┌─────────────────────────────────┐      ┌──────────────────────────────────┐
│ SkyMaster Backend (Scheduler)  │      │  GPU Worker (this script)        │
├─────────────────────────────────┤      ├──────────────────────────────────┤
│  • Assigns queued jobs to node │  ←→  │  • Heartbeat + claim next job     │
│  • Stores metrics for charts   │      │  • Runs actual training          │
│  • Publishes to model market    │      │  • Reports metrics periodically  │
└─────────────────────────────────┘      └──────────────────────────────────┘
```

## Adapting to your models

The `run_training()` function is a skeleton. You need to adapt it:

1. Add code to download dataset and base model from the URI provided by SkyMaster
2. Add your actual training loop
3. Call `report_metric()` every N steps to update the loss chart
4. After training completes, upload the final model to permanent storage and pass the URI back

## Pricing

The worker reports `gpu_hours_used`, server calculates cost based on your configured price per hour.

## Monitoring

Check `worker.log` for debugging. The worker will automatically reconnect after network outages.
