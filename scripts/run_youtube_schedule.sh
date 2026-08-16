#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
. ./.env
set +a
export PYTHONPATH="$ROOT"
PY="${OPENMONTAGE_PYTHON:-$ROOT/venv/bin/python3}"
exec "$PY" scripts/schedule_youtube_today.py "$@"
