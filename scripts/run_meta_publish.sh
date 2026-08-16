#!/usr/bin/env bash
# Run Meta publisher (FB scheduled + IG immediate) for today's active projects.
# Uses config/publish_schedule.json to discover which projects are active.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
. ./.env
set +a
export PYTHONPATH="$ROOT"
PY="${OPENMONTAGE_PYTHON:-$ROOT/venv/bin/python3}"

# Read active_projects array from config JSON
PROJECTS=$("$PY" -c "import json;print(' '.join(json.load(open('config/publish_schedule.json'))['active_projects']))")
exec "$PY" scripts/publish_meta.py $PROJECTS
