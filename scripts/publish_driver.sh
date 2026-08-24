#!/usr/bin/env bash
# Publish driver: find a python with google-auth, dry-run the publisher, write STATUS file.
# Usage: publish_driver.sh <candidate_id> [dry-run|publish]
set -u
ROOT="$HOME/OpenMontage"
CAND="${1:-cand_62804ede094ca10c}"
MODE="${2:-dry-run}"
STATUS="$ROOT/.scr_pub_status.txt"
: > "$STATUS"
W() { echo "$1" >> "$STATUS"; }

W "MODE=$MODE"

# Find a python interpreter that can import google-auth and googleapiclient.
PY=""
for cand in \
  /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python \
  "$ROOT/.venv/bin/python" "$ROOT/venv/bin/python" \
  "$HOME/.venv/bin/python" "$HOME/OpenMontage/.venv/bin/python"; do
  if [ -x "$cand" ]; then
    if "$cand" -c "import google.auth, googleapiclient" >/dev/null 2>&1; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  # Fallback: pip-installed python3 on host
  if python3 -c "import google.auth, googleapiclient" >/dev/null 2>&1; then
    PY="$(command -v python3)"
  fi
fi
W "PY=${PY:-NONE}"

SEM=""
if [ "$MODE" = "publish" ]; then
  SEM="--no-dry-run-placeholder"
fi

run_in() {
  local env_cmd="$1"; shift
  local runner="$1"; shift
  "$@" > "$ROOT/.scr_pub_run.out" 2>&1
  echo "$?" >> "$STATUS"
}

RCOUT=""
if [ -n "$PY" ]; then
  cd "$ROOT"
  RCOUT=$(env PYTHONPATH="$ROOT" "$PY" "$ROOT/scripts/publish_manual_video.py" "projects/$CAND" ${MODE:+"--dry-run"} 2>&1)
  RCR=$?
  W "RUN_RC=$RCR"
  printf '%s\n' "$RCOUT" | tail -n 30 >> "$STATUS"
else
  W "no qualified python found"
  W "host python3 google import:$(python3 -c 'import google' 2>&1 | head -1)"
  W "worker python3 google import:$(docker exec openmontage_worker python3 -c 'import google' 2>&1 | head -1)"
fi
W "STATUS_DONE"