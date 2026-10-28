#!/usr/bin/env bash
# 一次性 hook：打印当前 git 分支状态，提醒后续 force-push 风险。
# 跑一次即退出，不保留任何状态。
set -uo pipefail

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'no-git')"
echo "branch=${BRANCH}"
if [ "${BRANCH}" = "main" ] || [ "${BRANCH}" = "master" ]; then
  echo "warn: 直接在 ${BRANCH} 上操作，force push 已被 force-push-guard mod 接管"
fi
