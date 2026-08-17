#!/usr/bin/env bash
# =============================================================================
# dev_video_stack.sh - 视频墙开发栈一键管理 (无 docker)
#
# 管理两个裸进程:
#   1. MediaMTX        /home/duoduo/tools/mediamtx (RTSP:8554 HLS:8888 API:9997)
#   2. 推流看门狗      scripts/dev_video_push_watchdog.sh (ffmpeg lavfi -> RTSP)
#
# 用法:
#   scripts/dev_video_stack.sh          # = start
#   scripts/dev_video_stack.sh start    # 幂等启动, 已在跑的组件跳过
#   scripts/dev_video_stack.sh stop     # 停 watchdog + ffmpeg + mediamtx
#   scripts/dev_video_stack.sh status   # 各组件存活状态
#
# 前置 (本脚本不负责启动):
#   - 后端 dev 栈 (uvicorn :8000), 且 drones 表已 seed FAKE-SIM-01/02
#   - 前端 next start :3000
# =============================================================================
set -u

MTX_DIR="/home/duoduo/tools"
MTX_LOG="/tmp/mediamtx.log"
WD_LOG="/tmp/watchdog_ffmpeg.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WD_SCRIPT="$SCRIPT_DIR/dev_video_push_watchdog.sh"

mtx_pid()  { pgrep -x mediamtx | head -1; }
wd_pid()   { pgrep -f "dev_video_push_watchdog.sh" | head -1; }
ff_count() { pgrep -x ffmpeg | wc -l; }
api_up()   { curl -sf -m 3 http://127.0.0.1:9997/v3/paths/list >/dev/null 2>&1; }

start() {
  # --- MediaMTX ---
  if [ -n "$(mtx_pid)" ] && api_up; then
    echo "[mediamtx] already running (pid $(mtx_pid))"
  else
    if [ -n "$(mtx_pid)" ]; then
      echo "[mediamtx] pid $(mtx_pid) alive but API dead, restarting"
      kill "$(mtx_pid)" 2>/dev/null; sleep 1
    fi
    ( cd "$MTX_DIR" && setsid nohup ./mediamtx mediamtx.yml \
        > "$MTX_LOG" 2>&1 < /dev/null & )
    sleep 2
    if api_up; then
      echo "[mediamtx] started (pid $(mtx_pid), log $MTX_LOG)"
    else
      echo "[mediamtx] FAILED to start, check $MTX_LOG"; return 1
    fi
  fi

  # --- watchdog (自管 ffmpeg) ---
  if [ -n "$(wd_pid)" ]; then
    echo "[watchdog] already running (pid $(wd_pid))"
  else
    setsid nohup bash "$WD_SCRIPT" > "$WD_LOG" 2>&1 < /dev/null &
    sleep 4
    if [ -n "$(wd_pid)" ]; then
      echo "[watchdog] started (pid $(wd_pid), log $WD_LOG)"
      echo "[ffmpeg]  $(ff_count) pusher(s) up (testsrc2/smptebars -> rtsp)"
    else
      echo "[watchdog] FAILED to start, check $WD_LOG"; return 1
    fi
  fi
  echo "video stack UP: rtsp://127.0.0.1:8554 / hls :8888 / api :9997"
}

stop() {
  echo "[watchdog] stopping..."
  pkill -f "dev_video_push_watchdog.sh" 2>/dev/null
  echo "[ffmpeg]  stopping..."
  pkill -x ffmpeg 2>/dev/null
  echo "[mediamtx] stopping..."
  pkill -x mediamtx 2>/dev/null
  sleep 1
  status
}

status() {
  local ok=0
  if api_up; then
    echo "[mediamtx] UP (pid $(mtx_pid), api ok)"
  else
    echo "[mediamtx] DOWN"; ok=1
  fi
  if [ -n "$(wd_pid)" ]; then
    echo "[watchdog] UP (pid $(wd_pid))"
  else
    echo "[watchdog] DOWN"; ok=1
  fi
  echo "[ffmpeg]  $(ff_count) pusher(s)"
  if [ "$ok" = 0 ]; then echo "video stack: HEALTHY"; else echo "video stack: DEGRADED"; fi
  return "$ok"
}

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac
