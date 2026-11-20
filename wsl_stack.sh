#!/usr/bin/env bash
# SkyMaster WSL 全栈一键启动：conda PG + 后端 + 南宁3机仿真 + 前端
# 用法: bash /home/duoduo/projects/skymaster-drone-platform/wsl_stack.sh
set -u
ROOT=/home/duoduo/projects/skymaster-drone-platform
export PATH="$HOME/miniconda3/envs/pg/bin:$PATH"

# pgrep -f would match the invoking shell itself (its cmdline contains the
# pattern), so use listening ports as the source of truth for "already up".
port_up() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

# 1) conda PostgreSQL（127.0.0.1:5432，PGDATA=~/pgdata）
if ! pg_isready -h 127.0.0.1 -p 5432 -q 2>/dev/null; then
  mkdir -p ~/pgdata/log
  pg_ctl -D ~/pgdata -l ~/pgdata/log/pg.log start
  sleep 2
fi
pg_isready -h 127.0.0.1 -p 5432 -q && echo "[PG] up (5432)" || { echo "[PG] FAILED"; exit 1; }

cd "$ROOT/backend"
export DATABASE_URL="postgresql+asyncpg://skymaster:skymaster@127.0.0.1:5432/skymaster"
export USE_FAKE_REDIS=true
export AUTH_OPTIONAL=true
export START_TELEMETRY_STACK=true
# sim 控制 API 的 sysid→命令端口注册表（必须覆盖全部仿真机）
export SIM_DRONES="1:15001,2:15002,3:15003"
# 视频栈跑在裸进程(非 docker)，mediamtx 用 127.0.0.1 而非容器主机名
export MEDIAMTX_API_URL="http://127.0.0.1:9997"
export MEDIAMTX_HLS_URL_BASE="http://127.0.0.1:8888"
export MEDIAMTX_RTSP_URL_BASE="rtsp://127.0.0.1:8554"

# 2) 后端 FastAPI (:8000)
if ! port_up 8000; then
  setsid nohup .venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 > /tmp/skymaster_backend.log 2>&1 < /dev/null &
  echo "[BE] launching..."
else
  echo "[BE] already running"
fi

# 3) 南宁 3 机仿真（sysid 1-3 -> udp 14550-14552）
if ! port_up 15001; then
  setsid nohup .venv/bin/python scripts/fake_drone_swarm.py \
    --count 3 --region Nanning --interval-ms 500 --command-http-base 15001 \
    > /tmp/skymaster_swarm.log 2>&1 < /dev/null &
  echo "[SIM] launching 3 drones..."
else
  echo "[SIM] already running"
fi

# 4) 前端 next dev (:3000, 0.0.0.0)
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"
cd "$ROOT/frontend"
if ! port_up 3000; then
  setsid nohup node node_modules/next/dist/bin/next dev -H 0.0.0.0 \
    > /tmp/next_dev.log 2>&1 < /dev/null &
  echo "[FE] launching..."
else
  echo "[FE] already running"
fi

echo "=== stack up: PG 5432 / BE 8000 / SIM 14550-14552 (cmd 15001-15003) / FE 3000 ==="
