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
PUBLISH_TZ="${PUBLISH_TZ:-$(jq -r '.timezone // "America/New_York"' "$SCHEDULE" 2>/dev/null || echo "America/New_York")}"
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
CALENDAR_TZ="${CALENDAR_TZ:-${PUBLISH_CALENDAR_TZ:-}}"
if [ -z "$CALENDAR_TZ" ]; then
  if [ "${PUBLISH_TZ:-}" = "UTC" ]; then
    CALENDAR_TZ="UTC"
  else
    CALENDAR_TZ="${PUBLISH_TZ:-America/New_York}"
  fi
fi
NEXT_DATE=$(TZ="$CALENDAR_TZ" date -d tomorrow +%F)
TODAY=$(TZ="$CALENDAR_TZ" date +%F)

# 3.5 Check if NO_ELIGIBLE_TOPIC was recorded for today.
if [[ -f "$ROOT/data/.no_eligible_topic_marker" ]]; then
  MARKER_DATE=$(TZ="$CALENDAR_TZ" date -r "$ROOT/data/.no_eligible_topic_marker" +%F 2>/dev/null || echo "")
  if [[ "${NEWS_DISCOVERY_PROVIDER:-muse}" == "muse" && "$MARKER_DATE" == "$TODAY" ]]; then
    log "Muse found no eligible topics today; skipping quota-driven retries."
    exit 0
  fi
  # If eligible candidates are available in curated or source feeds, remove stale marker and proceed
  if "$PY" -c "
import sys
from lib.fixed_niche.hybrid_discovery import HybridCandidateDiscovery
res = HybridCandidateDiscovery().discover_candidates(count=1)
sys.exit(0 if res.is_eligible else 1)
" 2>/dev/null; then
    log "Eligible candidates available in curated/source backlog; clearing stale .no_eligible_topic_marker."
    rm -f "$ROOT/data/.no_eligible_topic_marker"
  else
    MARKER_DATE=$(TZ="$CALENDAR_TZ" date -r "$ROOT/data/.no_eligible_topic_marker" +%F 2>/dev/null || echo "")
    if [[ "$MARKER_DATE" == "$TODAY" ]]; then
      log "NO_ELIGIBLE_TOPIC was recorded for today ($TODAY) and backlog is empty. Skipping retry loop to prevent infinite retry storms."
      exit 0
    fi
  fi
fi

# 4. Count projects scheduled for NEXT_DATE.
SCHEDULED_COUNT=$(jq --arg d "$NEXT_DATE" '
  [.active_projects[]? | select(type == "object" and (.publish_date // "") == $d)] | length
' "$SCHEDULE" 2>/dev/null || echo 0)
SCHEDULED_COUNT="${SCHEDULED_COUNT:-0}"
[[ "$SCHEDULED_COUNT" =~ ^[0-9]+$ ]] || SCHEDULED_COUNT=0

log "Schedule check for $NEXT_DATE (tomorrow in $CALENDAR_TZ, publish tz $PUBLISH_TZ): $SCHEDULED_COUNT/$EXPECTED_SUCCESS_COUNT projects scheduled."

if [[ "$SCHEDULED_COUNT" -ge "$EXPECTED_SUCCESS_COUNT" ]]; then
  PENDING_NATIVE="$ROOT/logs/strict_docker_publish/platform-schedule-$NEXT_DATE.pending"
  if [ -f "$PENDING_NATIVE" ]; then
    exec 199>>"$LOCK_FILE"
    if ! flock -n 199; then
      log "A strict publish pipeline run is active; deferring native scheduling retry."
      exit 0
    fi
    if [ -f "$PENDING_NATIVE" ]; then
      log "Retrying pending native scheduling for $NEXT_DATE."
      export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
      if STRICT_REQUIRE_NATIVE_SCHEDULE=1 "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$NEXT_DATE"; then
        rm -f "$PENDING_NATIVE"
      else
        log "Native scheduling retry failed; retaining pending marker."
        exit 1
      fi
    fi
  fi
  log "Next-day schedule requirement satisfied ($SCHEDULED_COUNT >= $EXPECTED_SUCCESS_COUNT). No retry needed."
  exit 0
fi

# 5. Requirement not met — trigger the strict pipeline.
MISSING_COUNT=$((EXPECTED_SUCCESS_COUNT - SCHEDULED_COUNT))
log "Next-day schedule has only $SCHEDULED_COUNT/$EXPECTED_SUCCESS_COUNT projects for $NEXT_DATE ($MISSING_COUNT needed). Triggering run_strict_docker_publish.sh..."
export EXPECTED_SUCCESS_COUNT="$MISSING_COUNT"
export ALLOW_PARTIAL_DAILY_BATCH="${ALLOW_PARTIAL_DAILY_BATCH:-1}"
# Ensure retry pipeline prioritizes tomorrow's missing quota rather than allocating to today
export TARGET_TODAY_COUNT="${TARGET_TODAY_COUNT:-0}"
exec "$ROOT/scripts/run_strict_docker_publish.sh"
