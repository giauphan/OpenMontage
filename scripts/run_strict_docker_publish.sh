#!/usr/bin/env bash
# Strict Docker publish workflow orchestrator.
# Runs entirely inside the openmontage_worker container on the server.
# Stages: prepare -> generate -> verify -> claude-validate -> publish -> cleanup.
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

# ===== Pre-flight: confirm we're inside Docker =====
stage 0 "preflight"
[ -f /.dockerenv ] || grep -qE 'docker|containerd' /proc/1/cgroup 2>/dev/null || fail "must run inside Docker container"
command -v python3 >/dev/null  || fail "python3 missing"
command -v ffmpeg   >/dev/null  || fail "ffmpeg missing"
command -v ffprobe  >/dev/null  || fail "ffprobe missing"
command -v claude   >/dev/null  || fail "claude CLI missing"
log "preflight OK (docker=$(hostname), py=$(python3 --version | awk '{print $2}'), claude=$(claude --version 2>&1 | head -1))"
write_state "preflight" "ok"

# ===== STAGE 1: PREPARE — clear stale projects + orphan schedule entries =====
stage 1 "prepare"

# 1a. Preserve every existing candidate until canonical Firebase records prove it published.
SCHEDULE="$ROOT/config/publish_schedule.json"
RETAINED_COUNT=$(find "$ROOT/projects" -mindepth 1 -maxdepth 1 -type d -name 'cand_*' 2>/dev/null | wc -l)
log "retained $RETAINED_COUNT existing candidate project directories pending canonical Firebase verification"
write_state "prepare-retain-projects" "ok" "retained=$RETAINED_COUNT"

# 1b. Preserve active schedule entries; failed, duplicate, and scheduled candidates remain retriable.
SCHEDULE_COUNT=$(jq '.active_projects | length' "$SCHEDULE")
log "retained $SCHEDULE_COUNT active schedule entries pending canonical Firebase verification"
write_state "prepare-retain-schedule" "ok" "retained=$SCHEDULE_COUNT"

# 1c. Clear stale publish state files (logs / state dirs).
rm -rf "$ROOT"/logs/news_produce_*.log "$ROOT"/logs/directors_*_result.json 2>/dev/null || true
log "stale publish state cleared"
write_state "prepare-clear-state" "ok"

# ===== STAGE 2: GENERATE — produce the video and all publish assets =====
stage 2 "generate"
GENERATE_LOG="$LOG_DIR/generate_${RUN_TS}.log"
export OPENMONTAGE_PYTHON=/usr/bin/python3
bash "$ROOT/scripts/run_daily_news_pipeline.sh" 2>&1 | tee "$GENERATE_LOG"
[ ${PIPESTATUS[0]} -eq 0 ] || fail "generation pipeline failed (see $GENERATE_LOG)"
write_state "generate" "ok"

# Collect the 3 newly generated project IDs from the latest produce log.
mapfile -t PROJECT_IDS < <(grep -h '^PROJECT_ID=' "$GENERATE_LOG" | tail -3 | cut -d= -f2)
[ "${#PROJECT_IDS[@]}" -eq 3 ] || fail "expected 3 projects from generation, got ${#PROJECT_IDS[@]}"
log "generated projects: ${PROJECT_IDS[*]}"
write_state "generate-projects" "ok" "projects=$(IFS=,; echo "${PROJECT_IDS[*]}")"

# ===== STAGE 3: STRICT VERIFICATION — video + metadata + schedule =====
stage 3 "strict-verification"
VERIFY_LOG="$LOG_DIR/verify_${RUN_TS}.log"
: > "$VERIFY_LOG"
VERIFY_OK=1

# Determine the next intended publish date: tomorrow in PUBLISH_TZ.
NEXT_DATE=$(TZ="$PUBLISH_TZ" date -d tomorrow +%F)
log "next publish date (local $PUBLISH_TZ): $NEXT_DATE"

for PID in "${PROJECT_IDS[@]}"; do
  PDIR="$ROOT/projects/$PID"
  log "verifying $PID"
  # 3a. Project directory exists.
  [ -d "$PDIR" ] || { log "FAIL $PID: project dir missing"; VERIFY_OK=0; continue; }
  # 3b. publish_metadata.json exists + valid JSON + has required fields.
  META="$PDIR/publish_metadata.json"
  [ -f "$META" ] || { log "FAIL $PID: publish_metadata.json missing"; VERIFY_OK=0; continue; }
  jq -e '.id and .title and .description and .yt_shorts and .ig_reels and .fb_video' "$META" >/dev/null 2>&1 \
    || { log "FAIL $PID: publish_metadata.json invalid/missing fields"; VERIFY_OK=0; continue; }
  # 3c. Render files exist and non-empty.
  for R in "renders/final_full_vi_9x16.mp4" "renders/final_reels_vi_9x16.mp4"; do
    [ -s "$PDIR/$R" ] || { log "FAIL $PID: render $R missing/empty"; VERIFY_OK=0; }
  done
  # 3d. Technical quality validation via validate_render_quality.py.
  python3 "$ROOT/scripts/validate_render_quality.py" "$PDIR" >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_render_quality failed"; VERIFY_OK=0; }
  # 3e. publish_metadata validation.
  python3 "$ROOT/scripts/validate_publish_metadata.py" "$PDIR" >> "$VERIFY_LOG" 2>&1 \
    || { log "FAIL $PID: validate_publish_metadata failed"; VERIFY_OK=0; }
  # 3f. Schedule has this project registered for NEXT_DATE.
  SCHEDULE_HAS=$(jq --arg pid "$PID" --arg d "$NEXT_DATE" \
    'any(.active_projects[]?; (.project_id // .) == $pid and (.publish_date // "") == $d)' \
    "$SCHEDULE" 2>/dev/null || echo false)
  [ "$SCHEDULE_HAS" = "true" ] || { log "FAIL $PID: not scheduled for $NEXT_DATE"; VERIFY_OK=0; }
done

[ "$VERIFY_OK" -eq 1 ] || { write_state "verify" "failed"; fail "verification failed (see $VERIFY_LOG)"; }
log "strict verification PASSED for all 3 projects"
write_state "verify" "ok"

# ===== STAGE 4: STRICT CLAUDE AGENT VALIDATION =====
stage 4 "claude-agent-validation"
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

# ===== STAGE 5: PUBLISH — for next intended publish date =====
stage 5 "publish"
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

# ===== STAGE 6: POST-PUBLISH CLEANUP =====
stage 6 "cleanup"
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

# ===== STAGE 7: FINAL STATE VERIFICATION =====
stage 7 "final-state"
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
RETAINED=$(find "$ROOT/projects" -mindepth 1 -maxdepth 1 -type d -name 'cand_*' 2>/dev/null | wc -l)
ACTIVE=$(jq '.active_projects | length' "$SCHEDULE")
log "retained unverified cand_* dirs: $RETAINED"
log "unrelated active_projects count: $ACTIVE"
[ "$FINAL_OK" -eq 1 ] || { write_state "final-state" "failed"; fail "generated publish cleanup incomplete"; }
log "final state clean for generated projects"
write_state "final-state" "ok"

log ""
log "===== STRICT DOCKER PUBLISH WORKFLOW COMPLETED ====="
log "all stages passed; 3 videos published for $NEXT_DATE; generated projects cleaned"
write_state "workflow" "completed"
exit 0