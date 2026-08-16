#!/usr/bin/env bash
set -euo pipefail
cd /home/genro68/OpenMontage
set -a
. ./.env
set +a
export PYTHONPATH=/home/genro68/OpenMontage
exec /home/genro68/OpenMontage/venv/bin/python3 scripts/schedule_youtube_today.py "$@"
