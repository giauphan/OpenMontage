#!/usr/bin/env bash
# OpenMontage - Retry daily automated pipeline if next-day schedule is incomplete.
#
# Idempotent catch-up / retry runner for the daily publishing pipeline.
# Checks whether tomorrow's schedule has the target number of scheduled projects
# (default 3). If already satisfied, exits 0 immediately (no-op).
# If fewer than target projects are scheduled and no pipeline is currently running,
# triggers run_strict_docker_publish.sh to generate, validate, and schedule them.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEDULE="${SCHEDULE:-$ROOT/config/publish_schedule.json}"
LOCK_FILE="${LOCK_FILE:-$ROOT/.strict_docker_publish.lock}"
PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"
EXPECTED_SUCCESS_COUNT="${EXPECTED_SUCCESS_COUNT:-3}"
PY="${OPENMONTAGE_PYTHON:-$(command -v python3)}"

log() { echo "[$(date -u +%FT%TZ)] [RETRY_RUNNER] $*"; }

# 1. Non-blocking check on primary pipeline lock.
# If a pipeline run is currently in progress, do not interfere.
if [ -f "$LOCK_FILE" ]; then
  exec 199>>"$LOCK_FILE"
  if ! flock -n 199; then
    log "A strict publish pipeline run is currently active (lock held). Skipping retry check."
    exit 0
  fi
  flock -u 199
  exec 199>&-
fi

# 2. Check publish schedule integrity.
if [ ! -f "$SCHEDULE" ]; then
  log "WARNING: publish schedule missing at $SCHEDULE. Triggering pipeline."
  exec "$ROOT/scripts/run_strict_docker_publish.sh"
fi

# 3. Calculate target next-day date.
NEXT_DATE=$(TZ="$PUBLISH_TZ" date -d tomorrow +%F)
TODAY=$(TZ="$PUBLISH_TZ" date +%F)

# 4. Count projects scheduled for NEXT_DATE.
SCHEDULED_COUNT=$(jq --arg d "$NEXT_DATE" '
  [.active_projects[]? | select(type == "object" and (.publish_date // "") == $d)] | length
' "$SCHEDULE" 2>/dev/null || echo 0)

log "Schedule check for $NEXT_DATE (tomorrow in $PUBLISH_TZ): $SCHEDULED_COUNT/$EXPECTED_SUCCESS_COUNT projects scheduled."

if [ "$SCHEDULED_COUNT" -ge "$EXPECTED_SUCCESS_COUNT" ]; then
  log "Next-day schedule requirement satisfied ($SCHEDULED_COUNT >= $EXPECTED_SUCCESS_COUNT). No retry needed."
  exit 0
fi

# 5. Requirement not met — trigger the strict pipeline.
log "Next-day schedule has only $SCHEDULED_COUNT/$EXPECTED_SUCCESS_COUNT projects for $NEXT_DATE. Triggering run_strict_docker_publish.sh..."
exec "$ROOT/scripts/run_strict_docker_publish.sh"
