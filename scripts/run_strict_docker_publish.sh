#!/usr/bin/env bash
# Strict Docker publish workflow orchestrator.
# Runs entirely inside the openmontage_worker container on the server.
# Stages: prepare -> today-batch -> generate -> verify -> claude-validate -> publish -> cleanup -> final-state.
# Each stage is a hard gate; any failure stops the workflow before publishing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs/strict_docker_publish"
mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/run_${RUN_TS}.log"
STATE_FILE="$LOG_DIR/state_${RUN_TS}.json"

PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"
MAX_RETRIES="${CLAUDE_VALIDATION_RETRIES:-2}"
NEWSNOW_URL="${NEWSNOW_API_URL:-http://127.0.0.1:4444}"

log()  { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$RUN_LOG"; }
fail() { log "ERROR: $*"; exit 1; }
stage() { log ""; log "===== STAGE $1: $2 ====="; }

write_state() {
  local stage_name="$1" status="$2" extra="${3:-}"
  jq -n --arg ts "$(date -u +%FT%TZ)" --arg stage "$stage_name" --arg status "$status" \
       --arg extra "$extra" \
       '{stage:$stage, status:$status, ts:$ts, extra:$extra}' >> "$STATE_FILE"
}

cleanup_failed_generation() {
  local generate_log="$1"
  local pid dir schedule_has

  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    schedule_has=$(jq --arg pid "$pid" \
      'any(.active_projects[]?; (.project_id // .) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
    if [ "$schedule_has" = "true" ]; then
      log "preserving scheduled failed-generation project: $pid"
      continue
    fi
    for dir in "$ROOT/projects/$pid" "$ROOT/projects_news/$pid"; do
      if [ -d "$dir" ]; then
        rm -rf "$dir"
        log "cleanup failed-generation project: $pid"
      fi
    done
  done < <(
    grep -h 'PROJECT_ID=' "$generate_log" 2>/dev/null |
      sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' |
      sort -u
  )
}

# ===== Pre-flight: confirm we're inside Docker =====
stage 0 "preflight"
if [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" != "1" ]; then
  [ -f /.dockerenv ] || grep -qE 'docker|containerd' /proc/1/cgroup 2>/dev/null || fail "must run inside Docker container"
fi
command -v python3 >/dev/null  || fail "python3 missing"
command -v ffmpeg   >/dev/null  || fail "ffmpeg missing"
command -v ffprobe  >/dev/null  || fail "ffprobe missing"
command -v claude   >/dev/null  || fail "claude CLI missing"
log "preflight OK (docker=$(hostname), py=$(python3 --version | awk '{print $2}'), claude=$(claude --version 2>&1 | head -1))"
write_state "preflight" "ok"

# ===== STAGE 1: PREPARE — isolate due-today batch from next-day generation =====
stage 1 "prepare"
SCHEDULE="$ROOT/config/publish_schedule.json"
[ -f "$SCHEDULE" ] || fail "publish schedule missing: $SCHEDULE"
jq -e '.active_projects and (.active_projects | type == "array")' "$SCHEDULE" >/dev/null \
  || fail "schedule invalid"

TODAY=$(TZ="$PUBLISH_TZ" date +%F)
NEXT_DATE=$(TZ="$PUBLISH_TZ" date -d tomorrow +%F)
mapfile -t TODAY_PROJECT_IDS < <(jq -r --arg d "$TODAY" \
  '.active_projects[]? | select((.publish_date // "") == $d) | (.project_id // empty)' "$SCHEDULE")
log "today publish date (local $PUBLISH_TZ): $TODAY"
log "next publish date (local $PUBLISH_TZ): $NEXT_DATE"
log "due today projects: ${TODAY_PROJECT_IDS[*]:-none}"
write_state "prepare" "ok" "today=$TODAY next=$NEXT_DATE due=$(IFS=,; echo "${TODAY_PROJECT_IDS[*]}")"

# ===== STAGE 2: TODAY BATCH — verify, Claude validate, publish, cleanup =====
stage 2 "today-batch"
TODAY_PUBLISHED_PIDS=()
if [ "${#TODAY_PROJECT_IDS[@]}" -gt 0 ]; then
  TODAY_VERIFY_LOG="$LOG_DIR/today_verify_${RUN_TS}.log"
  TODAY_CLAUDE_LOG="$LOG_DIR/today_claude_validate_${RUN_TS}.log"
  TODAY_PUBLISH_LOG="$LOG_DIR/today_publish_${RUN_TS}.log"
  : > "$TODAY_VERIFY_LOG"
  : > "$TODAY_CLAUDE_LOG"
  : > "$TODAY_PUBLISH_LOG"
  TODAY_OK=1

  for PID in "${TODAY_PROJECT_IDS[@]}"; do
    PDIR="$ROOT/projects/$PID"
    [ -d "$PDIR" ] || { log "FAIL today $PID: project dir missing"; TODAY_OK=0; continue; }
    META="$PDIR/publish_metadata.json"
    [ -f "$META" ] || { log "FAIL today $PID: publish_metadata.json missing"; TODAY_OK=0; continue; }
    jq -e '.id and .title and .description and .yt_shorts and .ig_reels and .fb_video' "$META" >/dev/null 2>&1 \
      || { log "FAIL today $PID: publish_metadata invalid"; TODAY_OK=0; continue; }
    python3 "$ROOT/scripts/validate_render_quality.py" "$PDIR" >> "$TODAY_VERIFY_LOG" 2>&1 \
      || { log "FAIL today $PID: validate_render_quality failed"; TODAY_OK=0; continue; }
    python3 "$ROOT/scripts/validate_publish_metadata.py" "$PDIR" >> "$TODAY_VERIFY_LOG" 2>&1 \
      || { log "FAIL today $PID: validate_publish_metadata failed"; TODAY_OK=0; continue; }
    VALIDATION_PASSED=0
    for ((retry=1; retry<=MAX_RETRIES; retry++)); do
      if python3 "$ROOT/scripts/claude_agent_validation.py" "$PDIR" --strict --retry "$MAX_RETRIES" \
          >> "$TODAY_CLAUDE_LOG" 2>&1; then
        VALIDATION_PASSED=1
        break
      fi
      log "today Claude validation attempt $retry/$MAX_RETRIES failed for $PID"
    done
    if [ "$VALIDATION_PASSED" -ne 1 ]; then
      log "FAIL today $PID: Claude validation failed"
      TODAY_OK=0
    fi
  done
  [ "$TODAY_OK" -eq 1 ] || { write_state "today-batch" "failed"; fail "today validation failed"; }

  for PID in "${TODAY_PROJECT_IDS[@]}"; do
    PDIR="$ROOT/projects/$PID"
    log "publishing today $PID for $TODAY"
    if python3 "$ROOT/scripts/publish_manual_video.py" "$PDIR" --date "$TODAY" >> "$TODAY_PUBLISH_LOG" 2>&1; then
      TODAY_PUBLISHED_PIDS+=("$PID")
    else
      log "FAIL today $PID: publish failed"
      TODAY_OK=0
    fi
  done

  [ "$TODAY_PUBLISHED_PIDS" ] || true
  [ ${#TODAY_PUBLISHED_PIDS[@]} -eq ${#TODAY_PROJECT_IDS[@]} ] || TODAY_OK=0
  [ "$TODAY_OK" -eq 1 ] || { write_state "today-batch" "failed"; fail "today publish failed"; }

  for PID in "${TODAY_PUBLISHED_PIDS[@]}"; do
    [ ! -d "$ROOT/projects/$PID" ] || { log "FAIL today $PID: project dir remains"; TODAY_OK=0; }
    SCHEDULE_HAS=$(jq --arg pid "$PID" 'any(.active_projects[]?; (.project_id // .) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
    [ "$SCHEDULE_HAS" = "false" ] || { log "FAIL today $PID: still scheduled"; TODAY_OK=0; }
  done
  [ "$TODAY_OK" -eq 1 ] || { write_state "today-batch" "failed"; fail "today cleanup failed"; }
  log "today batch completed: ${TODAY_PUBLISHED_PIDS[*]}"
else
  log "no due projects for today"
fi
write_state "today-batch" "ok" "published=$(IFS=,; echo "${TODAY_PUBLISHED_PIDS[*]}")"

# ===== STAGE 3: GENERATE — produce next-day video and assets =====
stage 3 "generate"
GENERATE_LOG="$LOG_DIR/generate_${RUN_TS}.log"
export OPENMONTAGE_PYTHON=/usr/bin/python3
set +e
bash "$ROOT/scripts/run_daily_news_pipeline.sh" 2>&1 | tee "$GENERATE_LOG"
GEN_STATUS="${PIPESTATUS[0]}"
set -e

if [ "$GEN_STATUS" -ne 0 ]; then
  cleanup_failed_generation "$GENERATE_LOG"
  write_state "generate" "failed"
  fail "generation pipeline failed (see $GENERATE_LOG)"
fi
write_state "generate" "ok"

# Collect the 3 newly generated project IDs from the latest produce log.
mapfile -t PROJECT_IDS < <(grep -h 'PROJECT_ID=' "$GENERATE_LOG" | sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' | tail -3)
[ "${#PROJECT_IDS[@]}" -eq 3 ] || fail "expected 3 projects from generation, got ${#PROJECT_IDS[@]}"
log "generated projects: ${PROJECT_IDS[*]}"
write_state "generate-projects" "ok" "projects=$(IFS=,; echo "${PROJECT_IDS[*]}")"

# ===== STAGE 4: STRICT VERIFICATION — next-day video + metadata + schedule =====
stage 4 "strict-verification"
VERIFY_LOG="$LOG_DIR/verify_${RUN_TS}.log"
: > "$VERIFY_LOG"
VERIFY_OK=1

for PID in "${PROJECT_IDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "verifying $PID"
  # 4a. Project directory exists.
  [ -d "$PDIR" ] || { log "FAIL $PID: project dir missing"; VERIFY_OK=0; continue; }
  # 4b. publish_metadata.json exists + valid JSON + has required fields.
  META="$PDIR/publish_metadata.json"
  [ -f "$META" ] || { log "FAIL $PID: publish_metadata.json missing"; VERIFY_OK=0; continue; }
  jq -e '.id and .title and .description and .yt_shorts and .ig_reels and .fb_video' "$META" >/dev/null 2>&1 \
    || { log "FAIL $PID: publish_metadata.json invalid/missing fields"; VERIFY_OK=0; continue; }
  # 4c. Render files exist and non-empty.
  for R in "renders/final_full_vi_9x16.mp4" "renders/final_reels_vi_9x16.mp4"; do
    [ -s "$PDIR/$R" ] || { log "FAIL $PID: render $R missing/empty"; VERIFY_OK=0; }
  done
  # 4d. Technical quality validation via validate_render_quality.py.
  python3 "$ROOT/scripts/validate_render_quality.py" "$PDIR" >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_render_quality failed"; VERIFY_OK=0; }
  # 4e. publish_metadata validation.
  python3 "$ROOT/scripts/validate_publish_metadata.py" "$PDIR" >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_publish_metadata failed"; VERIFY_OK=0; }
  # 4f. Schedule has this project registered for NEXT_DATE.
  SCHEDULE_HAS=$(jq --arg pid "$PID" --arg d "$NEXT_DATE" \
    'any(.active_projects[]?; (.project_id // .) == $pid and (.publish_date // "") == $d)' \
    "$SCHEDULE" 2>/dev/null || echo false)
  [ "$SCHEDULE_HAS" = "true" ] || { log "FAIL $PID: not scheduled for $NEXT_DATE"; VERIFY_OK=0; }
done

[ "$VERIFY_OK" -eq 1 ] || { write_state "verify" "failed"; fail "verification failed (see $VERIFY_LOG)"; }
log "strict verification PASSED for all 3 projects"
write_state "verify" "ok"

# ===== STAGE 5: STRICT CLAUDE AGENT VALIDATION =====
stage 5 "claude-agent-validation"
CLAUDE_LOG="$LOG_DIR/claude_validate_${RUN_TS}.log"
: > "$CLAUDE_LOG"
CLAUDE_OK=1
VALIDATED_PIDS=()

for PID in "${PROJECT_IDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "claude validating $PID"
  VALIDATION_PASSED=0
  for ((retry=1; retry<=MAX_RETRIES; retry++)); do
    log "attempt $retry/$MAX_RETRIES for $PID"
    if python3 "$ROOT/scripts/claude_agent_validation.py" "$PDIR" --strict --retry "$MAX_RETRIES" \
        >> "$CLAUDE_LOG" 2>&1; then
      VALIDATION_PASSED=1
      break
    fi
    log "attempt $retry failed for $PID"
  done
  if [ "$VALIDATION_PASSED" -eq 1 ]; then
    log "claude validation PASSED for $PID"
    VALIDATED_PIDS+=("$PID")
  else
    log "claude validation FAILED for $PID"
    CLAUDE_OK=0
  fi
done

[ "$CLAUDE_OK" -eq 1 ] || { write_state "claude-validate" "failed"; fail "claude validation failed (see $CLAUDE_LOG)"; }
log "claude agent strict validation PASSED for all projects: ${VALIDATED_PIDS[*]}"
write_state "claude-validate" "ok" "validated=$(IFS=,; echo "${VALIDATED_PIDS[*]}")"

# ===== STAGE 6: PUBLISH — next-day batch =====
stage 6 "publish"
PUBLISH_LOG="$LOG_DIR/publish_${RUN_TS}.log"
: > "$PUBLISH_LOG"
PUBLISH_OK=1
PUBLISHED_PIDS=()

for PID in "${VALIDATED_PIDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "publishing $PID for $NEXT_DATE"
  if python3 "$ROOT/scripts/publish_manual_video.py" "$PDIR" --date "$NEXT_DATE" >> "$PUBLISH_LOG" 2>&1; then
    log "publish OK: $PID"
    PUBLISHED_PIDS+=("$PID")
  else
    log "publish FAILED: $PID"
    PUBLISH_OK=0
  fi
done

[ "$PUBLISH_OK" -eq 1 ] || { write_state "publish" "failed"; fail "publish failed (see $PUBLISH_LOG)"; }
[ "${#PUBLISHED_PIDS[@]}" -eq 3 ] || { write_state "publish" "partial"; fail "published ${#PUBLISHED_PIDS[@]}/3"; }
log "all 3 projects published: ${PUBLISHED_PIDS[*]}"
write_state "publish" "ok" "published=$(IFS=,; echo "${PUBLISHED_PIDS[*]}")"

# ===== STAGE 7: POST-PUBLISH CLEANUP =====
stage 7 "cleanup"
CLEANUP_LOG="$LOG_DIR/cleanup_${RUN_TS}.log"
: > "$CLEANUP_LOG"
CLEANUP_OK=1

for PID in "${PUBLISHED_PIDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  if [ -d "$PDIR" ]; then
    log "FAIL cleanup $PID: project dir still exists"
    CLEANUP_OK=0
  else
    log "cleanup OK: $PID project dir removed"
  fi
  SCHEDULE_HAS=$(jq --arg pid "$PID" \
    'any(.active_projects[]?; (.project_id // .) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
  if [ "$SCHEDULE_HAS" = "true" ]; then
    log "FAIL cleanup $PID: still in active_projects"
    CLEANUP_OK=0
  else
    log "cleanup OK: $PID removed from schedule"
  fi
done

[ "$CLEANUP_OK" -eq 1 ] || { write_state "cleanup" "failed"; fail "cleanup verification failed"; }
log "cleanup verified for all published projects"
write_state "cleanup" "ok"

# ===== STAGE 8: FINAL STATE VERIFICATION =====
stage 8 "final-state"
FINAL_OK=1
for PID in "${PROJECT_IDS[@]}"; do
  if [ -d "$ROOT/projects/$PID" ]; then
    log "FAIL final state $PID: generated project dir remains"
    FINAL_OK=0
  fi
  SCHEDULE_HAS=$(jq --arg pid "$PID" \
    'any(.active_projects[]?; (.project_id // .) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
  if [ "$SCHEDULE_HAS" = "true" ]; then
    log "FAIL final state $PID: generated project remains scheduled"
    FINAL_OK=0
  fi
done
[ "$FINAL_OK" -eq 1 ] || { write_state "final-state" "failed"; fail "generated publish cleanup incomplete"; }

log "removing stale orphaned projects"
"$ROOT/scripts/clear_stale_projects.sh" --all | tee -a "$RUN_LOG"

RETAINED=$(find "$ROOT/projects" -mindepth 1 -maxdepth 1 -type d -name 'cand_*' 2>/dev/null | wc -l)
ACTIVE=$(jq '.active_projects | length' "$SCHEDULE")
log "retained scheduled cand_* dirs: $RETAINED"
log "active_projects count: $ACTIVE"
log "final state clean for generated projects"
write_state "final-state" "ok"

log ""
log "===== STRICT DOCKER PUBLISH WORKFLOW COMPLETED ====="
log "all stages passed; today and next-day videos published; generated projects cleaned"
write_state "workflow" "completed"
exit 0
