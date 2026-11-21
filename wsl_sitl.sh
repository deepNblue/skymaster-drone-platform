#!/usr/bin/env bash
# PX4 SITL 双向 MAVLink 联调栈（独立于 wsl_stack.sh 的 fake_drone 演示栈）
#
# 与 wsl_stack.sh 的区别：
#   - wsl_stack.sh        : fake_drone_swarm 单向发遥测 + HTTP 命令旁路（3 机演示）
#   - wsl_sitl.sh (本文件) : sitl_mavlink_sim 双向 MAVLink（遥测入 + COMMAND_LONG/ACK 出）
#
# 默认端口 14550，与 fake_drone_swarm 冲突——两者不要同时跑。
# 用法：
#   SITL_PORT=14560 bash wsl_sitl.sh          # 起在 14560，避开主栈
#   bash wsl_sitl.sh --check                  # 只跑双向链路自检（不启进程）
set -u
ROOT=/home/duoduo/projects/skymaster-drone-platform
PORT="${SITL_PORT:-14550}"
STATE_PORT="${SITL_STATE_PORT:-15901}"
PROBE_LOG=/tmp/skymaster_sitl.log

if [[ "${1:-}" == "--check" ]]; then
  cd "$ROOT/backend"
  MAVLINK20=1 .venv/bin/python -m pytest \
    tests/test_sitl_mavlink_roundtrip.py -q
  exit $?
fi

cd "$ROOT/backend"
if ! ss -ltn 2>/dev/null | grep -q ":8000 "; then
  echo "请先运行 bash wsl_stack.sh 拉起后端与 PG" >&2
  exit 1
fi

# 关键：pymavlink 必须 MAVLINK20=1 才加载 v20 COMMAND_ACK/MISSION_* 字段
export MAVLINK20=1
export PYTHONPATH="$ROOT/backend"

if ! pgrep -f "sitl_mavlink_sim.py.*--port $PORT" >/dev/null 2>&1; then
  setsid nohup .venv/bin/python scripts/sitl_mavlink_sim.py \
    --system-id 1 --host 127.0.0.1 --port "$PORT" \
    --state-http-port "$STATE_PORT" --interval-ms 200 \
    > "$PROBE_LOG" 2>&1 < /dev/null &
  echo "[SITL] launching sysid=1 udpout:127.0.0.1:$PORT state=:$STATE_PORT"
else
  echo "[SITL] already running on $PORT"
fi

sleep 2
if curl -s "http://127.0.0.1:$STATE_PORT/state" >/dev/null 2>&1; then
  echo "[SITL] state probe OK: http://127.0.0.1:$STATE_PORT/state"
else
  echo "[SITL] state probe FAILED; see $PROBE_LOG" >&2
  exit 1
fi
echo "=== 双向联调栈: SITL udpout:$PORT → connector udpin:$PORT (MAVLINK20=1) ==="
