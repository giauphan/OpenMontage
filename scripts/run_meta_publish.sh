#!/usr/bin/env bash
# Run Meta publisher (FB scheduled + IG immediate) for today's active projects.
# Uses config/publish_schedule.json to discover which projects are active.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
export PYTHONPATH="$ROOT"

if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi

PROJECTS=$("$PY" -c "import json;print(' '.join(json.load(open('config/publish_schedule.json'))['active_projects']))")
exec "$PY" scripts/publish_meta.py $PROJECTS
