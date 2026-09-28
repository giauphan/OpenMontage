#!/usr/bin/env bash
# Strict Docker publish workflow orchestrator.
# Runs entirely inside the openmontage_worker container on the server.
# Stages: prepare -> today-batch -> generate -> verify -> claude-validate -> publish -> cleanup -> final-state.
# Each stage is a hard gate; any failure stops the workflow before publishing.
set -euo pipefail

export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:/app/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export FACEBOOK_PUBLISH_ENABLED=0

LOG_DIR="$ROOT/logs/strict_docker_publish"
mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/run_${RUN_TS}.log"
STATE_FILE="$LOG_DIR/state_${RUN_TS}.json"

PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"
MAX_RETRIES="${CLAUDE_VALIDATION_RETRIES:-3}"
GENERATION_RETRIES="${DAILY_GENERATION_RETRIES:-2}"
NEWSNOW_URL="${NEWSNOW_API_URL:-http://127.0.0.1:4444}"
PY="${OPENMONTAGE_PYTHON:-$(command -v python3)}"

log()  { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$RUN_LOG"; }
fail() {
  local msg="$*"
  log "ERROR: $msg"
  if [ -n "${CURRENT_STAGE:-}" ] && [ -n "${PY:-}" ]; then
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "$CURRENT_STAGE" \
      --error-type "STAGE_FAILURE" --message "$msg" || true
  fi
  exit 1
}
stage() {
  CURRENT_STAGE="$2"
  log ""
  log "===== STAGE $1: $2 ====="
}

write_state() {
  local stage_name="$1" status="$2" extra="${3:-}"
  jq -n --arg ts "$(date -u +%FT%TZ)" --arg stage "$stage_name" --arg status "$status" \
       --arg extra "$extra" \
       '{stage:$stage, status:$status, ts:$ts, extra:$extra}' >> "$STATE_FILE"
}

cleanup_system_disk_space() {
  log "running pre-flight disk cleanup to prevent low-disk failures..."
  # Clean old temporary directories in /tmp produced by puppeteer / chromium inside worker
  rm -rf /tmp/puppeteer_dev_chrome_profile-* 2>/dev/null || true
  rm -rf /tmp/hyperframes-* 2>/dev/null || true
  rm -rf /tmp/temp_ig_* 2>/dev/null || true

  # Clean old temporary logs in /app/logs
  find "$ROOT/logs" -type f -name "*.log" -mtime +7 -delete 2>/dev/null || true

  local avail_mb
  avail_mb=$(df -m /tmp | awk 'NR==2 {print $4}')
  log "available disk space on /tmp: ${avail_mb}MB"
}

cleanup_failed_generation() {
  local generate_log="$1"
  local pid dir schedule_has

  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    schedule_has=$(jq --arg pid "$pid" \
      'any(.active_projects[]?; (if type == "object" then .project_id else . end) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
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
cleanup_system_disk_space
if [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" != "1" ]; then
  [ -f /.dockerenv ] || grep -qE 'docker|containerd|lxc|init' /proc/1/cgroup 2>/dev/null || [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" = "1" ] || fail "must run inside Docker container"
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

# ===== STAGE 2: TODAY BATCH — verify native scheduling =====
stage 2 "today-batch"
if [ "${#TODAY_PROJECT_IDS[@]}" -gt 0 ]; then
  log "verifying native scheduling for ${#TODAY_PROJECT_IDS[@]} due-today projects"
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$TODAY" >> "$RUN_LOG" 2>&1; then
    write_state "today-batch" "failed"
    fail "today native scheduling failed for existing queue entries"
  fi
  log "retained due-today projects for slot cron"
else
  log "no due projects for today"
fi
write_state "today-batch" "ok" "verified=$(IFS=,; echo "${TODAY_PROJECT_IDS[*]}")"

# ===== STAGE 3: GENERATE — produce next-day video and assets =====
stage 3 "generate"
export OPENMONTAGE_PYTHON="$PY"
PROJECT_IDS=()
GENERATION_ATTEMPT=0
GEN_STATUS=1
if [ "${STRICT_PUBLISH_SKIP_GENERATE:-0}" = "1" ]; then
  GENERATE_LOG=$(ls -t "$LOG_DIR"/generate_*.log | head -1)
  [ -f "$GENERATE_LOG" ] || fail "STRICT_PUBLISH_SKIP_GENERATE=1 but no generation log exists"
  mapfile -t PROJECT_IDS < <(grep -h 'PROJECT_ID=' "$GENERATE_LOG" | sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' | awk '!seen[$0]++')
  GEN_STATUS=0
  log "STRICT_PUBLISH_SKIP_GENERATE=1: reusing projects from $GENERATE_LOG"
else
  while [ "$GENERATION_ATTEMPT" -lt "$GENERATION_RETRIES" ]; do
    GENERATION_ATTEMPT=$((GENERATION_ATTEMPT + 1))
    GENERATE_LOG="$LOG_DIR/generate_${RUN_TS}_attempt${GENERATION_ATTEMPT}.log"
    log "generation attempt $GENERATION_ATTEMPT/$GENERATION_RETRIES"
    set +e
    bash "$ROOT/scripts/run_daily_news_pipeline.sh" 2>&1 | tee "$GENERATE_LOG"
    GEN_STATUS="${PIPESTATUS[0]}"
    set -e
    mapfile -t PROJECT_IDS < <(grep -h 'PROJECT_ID=' "$GENERATE_LOG" | sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' | awk '!seen[$0]++')
    if [ "$GEN_STATUS" -eq 0 ] && [ "${#PROJECT_IDS[@]}" -gt 0 ]; then
      break
    fi
    log "generation attempt $GENERATION_ATTEMPT failed (exit=$GEN_STATUS projects=${#PROJECT_IDS[@]})"
  done
fi

[ "${#PROJECT_IDS[@]}" -gt 0 ] || {
  cleanup_failed_generation "$GENERATE_LOG"
  write_state "generate" "failed"
  fail "expected at least 1 project from generation after $GENERATION_ATTEMPT attempts"
}
if [ "$GEN_STATUS" -ne 0 ]; then
  cleanup_failed_generation "$GENERATE_LOG"
  write_state "generate" "failed"
  fail "generation failed after $GENERATION_ATTEMPT attempts (exit=$GEN_STATUS; see $GENERATE_LOG)"
fi
write_state "generate" "ok"
log "generated projects: ${PROJECT_IDS[*]}"
write_state "generate-projects" "ok" "projects=$(IFS=,; echo "${PROJECT_IDS[*]}")"

# ===== STAGE 4: STRICT VERIFICATION — next-day video + metadata + schedule =====
stage 4 "strict-verification"
VERIFY_LOG="$LOG_DIR/verify_${RUN_TS}.log"
: > "$VERIFY_LOG"
VERIFY_OK_PIDS=()

for PID in "${PROJECT_IDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "verifying $PID"
  # 4a. Project directory exists.
  [ -d "$PDIR" ] || { log "FAIL $PID: project dir missing"; continue; }
  # 4b. publish_metadata.json exists + valid JSON + has required fields.
  META="$PDIR/publish_metadata.json"
  [ -f "$META" ] || { log "FAIL $PID: publish_metadata.json missing"; continue; }
  jq -e '.id and .title and .description and .yt_shorts and .ig_reels and .fb_video' "$META" >/dev/null 2>&1 \
    || { log "FAIL $PID: publish_metadata.json invalid/missing fields"; continue; }
  # 4c. Render files exist and non-empty.
  RENDER_OK=1
  for R in "renders/final_full_vi_9x16.mp4" "renders/final_reels_vi_9x16.mp4"; do
    [ -s "$PDIR/$R" ] || { log "FAIL $PID: render $R missing/empty"; RENDER_OK=0; }
  done
  [ "$RENDER_OK" -eq 1 ] || continue
  # 4d. Technical quality validation via validate_render_quality.py (reels max 60s for Shorts).
  "$PY" "$ROOT/scripts/validate_render_quality.py" "$PDIR" --reels-max-duration 60.0 >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_render_quality failed"; continue; }
  # 4e. publish_metadata validation.
  "$PY" "$ROOT/scripts/validate_publish_metadata.py" "$PDIR" >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_publish_metadata failed"; continue; }

  VERIFY_OK_PIDS+=("$PID")
done

[ "${#VERIFY_OK_PIDS[@]}" -gt 0 ] || { write_state "verify" "failed"; fail "all projects failed verification (see $VERIFY_LOG)"; }
log "strict verification PASSED for ${#VERIFY_OK_PIDS[@]} projects: ${VERIFY_OK_PIDS[*]}"
write_state "verify" "ok"

# ===== STAGE 5: STRICT CLAUDE AGENT VALIDATION =====
stage 5 "claude-agent-validation"
CLAUDE_LOG="$LOG_DIR/claude_validate_${RUN_TS}.log"
: > "$CLAUDE_LOG"
VALIDATED_PIDS=()

for PID in "${VERIFY_OK_PIDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "claude validating $PID"
  VALIDATION_PASSED=0
  for ((retry=1; retry<=MAX_RETRIES; retry++)); do
    log "attempt $retry/$MAX_RETRIES for $PID"
    if "$PY" "$ROOT/scripts/claude_agent_validation.py" "$PDIR" --strict --retry "$MAX_RETRIES" \
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
  fi
done

[ "${#VALIDATED_PIDS[@]}" -gt 0 ] || {
  write_state "claude-validate" "failed"
  fail "claude validation failed for all projects (see $CLAUDE_LOG)"
}
log "claude agent strict validation PASSED for ${#VALIDATED_PIDS[@]} projects: ${VALIDATED_PIDS[*]}"
write_state "claude-validate" "ok" "validated=$(IFS=,; echo "${VALIDATED_PIDS[*]}")"

# ===== STAGE 6: QUEUE — current-day recovery plus next-day schedule =====
stage 6 "queue"
QUEUE_OK=1
QUEUED_PIDS=()
TODAY_QUEUED_PIDS=()
NEXT_QUEUED_PIDS=()

SLOTS_JSON=$(jq -c '.slots.publish_slots_vn // ["09:15", "14:15", "21:15"]' "$SCHEDULE")
mapfile -t SLOTS < <(jq -r '.[]' <<< "$SLOTS_JSON")

declare -A TODAY_OCCUPIED=()
declare -A NEXT_OCCUPIED=()
while IFS= read -r SLOT; do
  [ -z "$SLOT" ] || TODAY_OCCUPIED["$SLOT"]=1
done < <(jq -r --arg date "$TODAY" '.active_projects[]? | select(type == "object" and (.publish_date // "") == $date) | .publish_time // empty' "$SCHEDULE")
while IFS= read -r SLOT; do
  [ -z "$SLOT" ] || NEXT_OCCUPIED["$SLOT"]=1
done < <(jq -r --arg date "$NEXT_DATE" '.active_projects[]? | select(type == "object" and (.publish_date // "") == $date) | .publish_time // empty' "$SCHEDULE")

NOW_EPOCH=$(date +%s)
TODAY_SLOTS=()
NEXT_SLOTS=()
for SLOT in "${SLOTS[@]}"; do
  SLOT_EPOCH=$(TZ="$PUBLISH_TZ" date -d "$TODAY $SLOT" +%s 2>/dev/null || echo 0)
  if [ "$SLOT_EPOCH" -gt "$((NOW_EPOCH + 1200))" ] && [ -z "${TODAY_OCCUPIED[$SLOT]:-}" ]; then
    TODAY_SLOTS+=("$SLOT")
  fi
  if [ -z "${NEXT_OCCUPIED[$SLOT]:-}" ]; then
    NEXT_SLOTS+=("$SLOT")
  fi
done

AVAILABLE_SLOT_COUNT=$((${#TODAY_SLOTS[@]} + ${#NEXT_SLOTS[@]}))
[ "$AVAILABLE_SLOT_COUNT" -ge "${#VALIDATED_PIDS[@]}" ] \
  || { write_state "queue" "failed"; fail "not enough unoccupied current/next-day publish slots ($AVAILABLE_SLOT_COUNT) for ${#VALIDATED_PIDS[@]} projects"; }

TMP_QUEUE=$(mktemp)
cp "$SCHEDULE" "$TMP_QUEUE"

TODAY_IDX=0
NEXT_IDX=0
for PID in "${VALIDATED_PIDS[@]}"; do
  if [ "$TODAY_IDX" -lt "${#TODAY_SLOTS[@]}" ]; then
    DATE="$TODAY"
    SLOT="${TODAY_SLOTS[$TODAY_IDX]}"
    TODAY_QUEUED_PIDS+=("$PID")
    TODAY_IDX=$((TODAY_IDX + 1))
  else
    DATE="$NEXT_DATE"
    SLOT="${NEXT_SLOTS[$NEXT_IDX]}"
    NEXT_QUEUED_PIDS+=("$PID")
    NEXT_IDX=$((NEXT_IDX + 1))
  fi

  jq --arg pid "$PID" --arg date "$DATE" --arg time "$SLOT" \
     '.active_projects += [{project_id: $pid, publish_date: $date, publish_time: $time}]' \
     "$TMP_QUEUE" > "$TMP_QUEUE.new" && mv "$TMP_QUEUE.new" "$TMP_QUEUE"
  log "queued $PID for $DATE slot $SLOT"
  QUEUED_PIDS+=("$PID")
done

jq -e '.active_projects and (.active_projects | type == "array")' "$TMP_QUEUE" >/dev/null 2>&1 \
  || { rm -f "$TMP_QUEUE"; write_state "queue" "failed"; fail "queued schedule invalid"; }
mv "$TMP_QUEUE" "$SCHEDULE"

[ "${#QUEUED_PIDS[@]}" -eq "${#VALIDATED_PIDS[@]}" ] \
  || { write_state "queue" "partial"; fail "queued ${#QUEUED_PIDS[@]}/${#VALIDATED_PIDS[@]} validated projects"; }

for PID in "${VALIDATED_PIDS[@]}"; do
  SCHEDULE_HAS=$(jq --arg pid "$PID" --arg today "$TODAY" --arg next "$NEXT_DATE" \
    'any(.active_projects[]?; ((if type == "object" then .project_id else . end) == $pid) and ((if type == "object" then .publish_date else "" end) | (. == $today or . == $next)))' \
    "$SCHEDULE" 2>/dev/null || echo false)
  [ "$SCHEDULE_HAS" = "true" ] || { log "FAIL queue $PID: not scheduled for $TODAY or $NEXT_DATE"; QUEUE_OK=0; }
  [ -d "$ROOT/projects/$PID" ] || { log "FAIL queue $PID: project dir must be retained for slot publisher"; QUEUE_OK=0; }
done
[ "$QUEUE_OK" -eq 1 ] || { write_state "queue" "failed"; fail "queue verification failed"; }

log "queued today: ${TODAY_QUEUED_PIDS[*]:-none}; queued next day: ${NEXT_QUEUED_PIDS[*]:-none}"
write_state "queue" "ok" "today=$(IFS=,; echo "${TODAY_QUEUED_PIDS[*]}") next=$(IFS=,; echo "${NEXT_QUEUED_PIDS[*]}")"

stage 6.5 "platform-schedule"
if [ "${#TODAY_QUEUED_PIDS[@]}" -gt 0 ]; then
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$TODAY" 2>&1 | tee -a "$RUN_LOG"; then
    write_state "platform-schedule" "failed" "date=$TODAY"
    fail "current-day YouTube scheduling failed; queued projects retained"
  fi
fi
if [ "${#NEXT_QUEUED_PIDS[@]}" -gt 0 ]; then
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$NEXT_DATE" 2>&1 | tee -a "$RUN_LOG"; then
    write_state "platform-schedule" "failed" "date=$NEXT_DATE"
    fail "next-day YouTube scheduling failed; queued projects retained"
  fi
fi
write_state "platform-schedule" "ok" "today=$(IFS=,; echo "${TODAY_QUEUED_PIDS[*]}") next=$(IFS=,; echo "${NEXT_QUEUED_PIDS[*]}")"

# ===== STAGE 7: STALE CLEANUP — remove obsolete unscheduled candidate dirs =====
stage 7 "cleanup"
log "removing stale orphaned projects"
"$ROOT/scripts/clear_stale_projects.sh" --all | tee -a "$RUN_LOG"

# ===== STAGE 8: FINAL STATE VERIFICATION =====
stage 8 "final-state"
FINAL_OK=1
for PID in "${QUEUED_PIDS[@]}"; do
  [ -d "$ROOT/projects/$PID" ] || { log "FAIL final state $PID: queued project dir missing"; FINAL_OK=0; }
  SCHEDULE_HAS=$(jq --arg pid "$PID" --arg today "$TODAY" --arg next "$NEXT_DATE" \
    'any(.active_projects[]?; ((if type == "object" then .project_id else . end) == $pid) and ((if type == "object" then .publish_date else "" end) | (. == $today or . == $next)))' \
    "$SCHEDULE" 2>/dev/null || echo false)
  [ "$SCHEDULE_HAS" = "true" ] || { log "FAIL final state $PID: queued project not scheduled for $TODAY or $NEXT_DATE"; FINAL_OK=0; }
done
[ "$FINAL_OK" -eq 1 ] || { write_state "final-state" "failed"; fail "queued state incomplete"; }

RETAINED=$(find "$ROOT/projects" -mindepth 1 -maxdepth 1 -type d -name 'cand_*' 2>/dev/null | wc -l)
ACTIVE=$(jq '.active_projects | length' "$SCHEDULE")
log "retained scheduled cand_* dirs: $RETAINED"
log "active_projects count: $ACTIVE"
log "final state queued for current/next day (YT native, IG on cron)"
write_state "final-state" "ok"

log ""
log "===== STRICT DOCKER PUBLISH WORKFLOW COMPLETED ====="
log "all stages passed; videos platform-scheduled; IG on slot cron"
write_state "workflow" "completed"
exit 0
