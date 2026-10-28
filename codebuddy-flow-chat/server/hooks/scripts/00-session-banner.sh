#!/usr/bin/env bash
# 一次性 hook 脚本 —— session 启动时跑一次就退出（视频里的 "hook.sh · 1x"）。
# 与 mod 的区别：这个脚本没有跨调用的内存，跑完进程就结束。
set -uo pipefail

echo "session=${CBC_SESSION_ID:-unknown} started at $(date '+%H:%M:%S')"
echo "mods=$(ls "${CBC_MODS_DIR:-./server/mods/builtin}" 2>/dev/null | wc -l | tr -d ' ') loaded (resident)"
