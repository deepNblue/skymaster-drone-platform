#!/usr/bin/env bash
# =============================================================================
# dev_video_push_watchdog.sh - 视频墙开发环境推流看门狗
#
# 用途: 无真机时用 ffmpeg lavfi 合成流模拟无人机相机 RTSP 推流, 经 MediaMTX
#       转 HLS, 供前端视频墙 (/dashboard/video-wall) 自动发现与播放验证。
#
# 前置:
#   1. MediaMTX 运行中 (默认 /home/duoduo/tools/mediamtx, RTSP :8554, HLS :8888,
#      API :9997), 配置建议 hlsAlwaysRemux: yes 避免无观看者 60s 后 HLS muxer
#      销毁造成前端冷启动 404。
#   2. 后端 dev 栈运行中 (SQLAlchemy+PG), drones 表里已有 FAKE-SIM-01/02
#      (scripts/seed_drones.py 注入)。
#   3. 后端 /api/v1/streams 会按 "drone-{uuid}" 路径名自动绑定 drone_id。
#
# 用法: nohup bash scripts/dev_video_push_watchdog.sh > /tmp/watchdog_ffmpeg.log 2>&1 &
#   停止: pkill -f dev_video_push_watchdog; pkill -f 'ffmpeg.*drone-'
#
# 踩坑记录:
#   - ffmpeg 8.x (libavformat 61) 已移除 -stimeout 选项, 加了会直接
#     "Unrecognized option" 退出; 断线重连交给本脚本外层看门狗。
#   - bash 的 UID 是只读变量, read 循环里必须换变量名 (DUID)。
#   - 系统 python3 无 asyncpg, 查 DB 必须用 backend/.venv/bin/python。
# =============================================================================
set -u
DB="postgresql://skymaster:skymaster@127.0.0.1:5432/skymaster"
VENV_PY="/home/duoduo/projects/skymaster-drone-platform/backend/.venv/bin/python"

while true; do
  IDS=$("$VENV_PY" - "$DB" <<'EOF'
import asyncio, sys
import asyncpg

async def m():
    c = await asyncpg.connect(sys.argv[1])
    rows = await c.fetch(
        "select id, sn from drones where sn like 'FAKE-SIM%' order by sn limit 2")
    await c.close()
    for r in rows:
        print(str(r["id"]), r["sn"])

asyncio.run(m())
EOF
)
  echo "$(date +%T) spawning ffmpeg for: $(echo "$IDS" | awk '{print $2}' | tr '\n' ' ')"
  PIDS=()
  while read -r DUID SN; do
    [ -z "$DUID" ] && continue
    if [ "$SN" = "FAKE-SIM-01" ]; then
      SRC="testsrc2=size=640x360:rate=15"
    else
      SRC="smptebars=size=640x360:rate=15"
    fi
    ffmpeg -re -f lavfi -i "$SRC" \
      -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -g 30 \
      -rtsp_transport tcp \
      -f rtsp "rtsp://127.0.0.1:8554/drone-$DUID" \
      > "/tmp/ff_${SN}.log" 2>&1 &
    PIDS+=($!)
  done <<< "$IDS"
  wait -n "${PIDS[@]}" 2>/dev/null || sleep 2
  echo "$(date +%T) an ffmpeg died, restarting in 2s"
  sleep 2
  kill "${PIDS[@]}" 2>/dev/null
done
