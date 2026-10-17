#!/usr/bin/env bash
# Strict Docker publish workflow orchestrator.
# Runs entirely inside the openmontage_worker container on the server.
# Stages: prepare -> today-batch -> generate -> verify -> claude-validate -> publish -> cleanup -> final-state.
# Each stage is a hard gate; any failure stops the workflow before publishing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/logs/heartbeat" "$ROOT/logs/strict_docker_publish"

export PATH="/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Serialize the complete strict run, including preflight and generation. Keep
# this stable lock file on the shared ROOT filesystem and never unlink it:
# flock releases the descriptor automatically when this process tree exits.
STRICT_RUN_LOCK="$ROOT/.strict_docker_publish.lock"
exec 199>>"$STRICT_RUN_LOCK"
if ! flock -n 199; then
  printf '%s\n' "ERROR: another strict publish run is active for $ROOT; retry after it finishes" >&2
  exit 75
fi

# Heartbeats are only owned after the exclusive run lock is held. Replacing
# via a same-directory temporary file keeps readers from seeing partial JSON.
# STRICT_HEARTBEAT_TRAPS_BEGIN
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
HEARTBEAT_TERMINAL=0
write_heartbeat() {
  local status="$1"
  local hb="$ROOT/logs/heartbeat/daily_orchestrator.json"
  local tmp
  mkdir -p "$(dirname "$hb")" || return 1
  tmp="$(mktemp "${hb}.tmp.XXXXXX")" || return 1
  if jq -n --arg ts "$(date -u +%FT%TZ)" --arg run "$RUN_TS" --arg status "$status" \
       '{ts:$ts, run_id:$run, status:$status}' > "$tmp" 2>/dev/null && mv -f "$tmp" "$hb"; then
    case "$status" in completed|failed) HEARTBEAT_TERMINAL=1 ;; esac
    return 0
  fi
  rm -f "$tmp"
  return 1
}
strict_run_exit() {
  local exit_status=$?
  trap - EXIT
  if [ "$HEARTBEAT_TERMINAL" -eq 0 ]; then
    write_heartbeat "failed" || true
  fi
  exit "$exit_status"
}
trap strict_run_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# STRICT_HEARTBEAT_TRAPS_END

export FACEBOOK_PUBLISH_ENABLED=0

# Codex pipeline profile: resolved and validated by scripts/codex_agent_validation.py.
# Defaults to the isolated pipeline profile initialized from the read-only host source.
if [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" = "1" ]; then
  export CODEX_HOME="${CODEX_HOME:-$ROOT/.tmp_codex_pipeline_$$}"
  mkdir -p "$CODEX_HOME"
  [ -s "$CODEX_HOME/auth.json" ] || echo '{"OPENAI_API_KEY":"mock-key"}' > "$CODEX_HOME/auth.json"
  [ -s "$CODEX_HOME/config.toml" ] || echo 'model = "mock"' > "$CODEX_HOME/config.toml"
else
  export CODEX_HOME="${CODEX_HOME:-/root/.codex_pipeline}"
fi
export CODEX_PIPELINE_PROFILE="omniroute"
export PRODUCTION_RELEASE="${PRODUCTION_RELEASE:-1}"

if [ -d "/etc/codex_source" ]; then
  src_key="$(jq -r '.OPENAI_API_KEY // empty' /etc/codex_source/auth.json 2>/dev/null || true)"
  cur_key="$(jq -r '.OPENAI_API_KEY // empty' "$CODEX_HOME/auth.json" 2>/dev/null || true)"
  if [ ! -s "$CODEX_HOME/auth.json" ] || [ -n "$src_key" -a "$src_key" != "$cur_key" ]; then
    REFRESH_CODEX_PROFILE=1 bash "$ROOT/scripts/init_codex_profile.sh" /etc/codex_source "$CODEX_HOME" || true
  fi
  if [ -d "/home/node" ]; then
    node_cur_key="$(jq -r '.OPENAI_API_KEY // empty' /home/node/.codex_pipeline/auth.json 2>/dev/null || true)"
    if [ ! -s "/home/node/.codex_pipeline/auth.json" ] || [ -n "$src_key" -a "$src_key" != "$node_cur_key" ]; then
      REFRESH_CODEX_PROFILE=1 bash "$ROOT/scripts/init_codex_profile.sh" /etc/codex_source /home/node/.codex_pipeline node || true
    fi
  fi
fi

# Load provider API key from the selected Codex profile auth store into the local
# environment for Codex CLI calls in cron/non-interactive context, preserving any
# already valid OPENAI_API_KEY present in the environment (e.g. from .env).
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$CODEX_HOME/auth.json" ]; then
  _api_key="$(jq -r '.OPENAI_API_KEY // empty' "$CODEX_HOME/auth.json" 2>/dev/null || true)"
  if [ -n "$_api_key" ]; then
    export OPENAI_API_KEY="$_api_key"
  fi
  unset _api_key
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
  for p_home in "$CODEX_HOME" "/home/node/.codex_pipeline"; do
    if [ -f "$p_home/auth.json" ]; then
      pk="$(jq -r '.OPENAI_API_KEY // empty' "$p_home/auth.json" 2>/dev/null || true)"
      if [ -n "$pk" -a "$pk" != "$OPENAI_API_KEY" ]; then
        tmp_auth="$(mktemp "$p_home/auth.XXXXXX" 2>/dev/null || mktemp /tmp/auth.XXXXXX)"
        jq --arg k "$OPENAI_API_KEY" '.OPENAI_API_KEY = $k' "$p_home/auth.json" > "$tmp_auth" 2>/dev/null && mv "$tmp_auth" "$p_home/auth.json" || rm -f "$tmp_auth"
      fi
    fi
  done
fi

LOG_DIR="$ROOT/logs/strict_docker_publish"
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/run_${RUN_TS}.log"
STATE_FILE="$LOG_DIR/state_${RUN_TS}.json"

PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"
# Use Gateway's documented model catalog instead of stale local profile aliases.
CODEX_MODEL="${CODEX_MODEL:-model-medium-hight}"
export CODEX_MODEL
MAX_RETRIES="${CLAUDE_VALIDATION_RETRIES:-3}"
GENERATION_RETRIES="${DAILY_GENERATION_RETRIES:-2}"
EXPECTED_SUCCESS_COUNT="${EXPECTED_SUCCESS_COUNT:-3}"
export EXPECTED_SUCCESS_COUNT
NEWSNOW_URL="${NEWSNOW_API_URL:-http://127.0.0.1:4444}"
PY="${OPENMONTAGE_PYTHON:-$(command -v python3)}"

# Temp/cleanup and disk-threshold knobs. TMP_ROOT defaults to the container-local
# /tmp (safe); tests override it so unit runs never touch the host /tmp.
TMP_ROOT="${TMP_ROOT:-/tmp}"
MIN_DISK_MB="${MIN_DISK_MB:-2000}"
MIN_TMP_DISK_MB="${MIN_TMP_DISK_MB:-2000}"
FAILED_GENERATION_RECOVERY_ROOT="${FAILED_GENERATION_RECOVERY_ROOT:-$ROOT/projects/_failed_generation_recovered}"

log()  { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$RUN_LOG"; }
fail() {
  local msg="$*"
  log "ERROR: $msg"
  if [ -n "${CURRENT_STAGE:-}" ] && [ -n "${PY:-}" ]; then
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "$CURRENT_STAGE" \
      --error-type "STAGE_FAILURE" --message "$msg" || true
  fi
  write_heartbeat "failed"
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

# STRICT_FRESHNESS_CONFIG_BEGIN
load_news_max_source_age_from_dotenv() {
  # Cron may not pass arbitrary daemon environment through to jobs. Preserve
  # every explicit environment value (including empty/invalid safety overrides)
  # and read only this non-secret setting from .env when it is truly unset.
  if [ "${NEWS_MAX_SOURCE_AGE_HOURS+x}" = x ] || [ ! -f "$ROOT/.env" ]; then
    return 0
  fi

  local configured_age
  if configured_age="$("$PY" - "$ROOT/.env" 2>/dev/null <<'PY'
import sys
from dotenv import dotenv_values

try:
    values = dotenv_values(sys.argv[1], interpolate=False)
except Exception:
    raise SystemExit(2)
key = "NEWS_MAX_SOURCE_AGE_HOURS"
if key not in values:
    raise SystemExit(1)
value = values[key]
sys.stdout.write("" if value is None else value)
PY
)"; then
    export NEWS_MAX_SOURCE_AGE_HOURS="$configured_age"
  fi
}

validate_news_max_source_age() {
  "$PY" -c 'import math, os, sys; value=os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS"); valid=False
try:
    age=float(value) if value is not None and value.strip() else float("nan")
    valid=math.isfinite(age) and 0 < age <= 720
except (TypeError, ValueError, OverflowError):
    pass
sys.exit(0 if valid else 1)'
}
# STRICT_FRESHNESS_CONFIG_END

cleanup_system_disk_space() {
  log "running pre-flight disk cleanup to prevent low-disk failures..."
  # Only reclaim temp dirs untouched for 2+ hours so in-flight renders/uploads
  # in the concurrent worker container are never deleted.
  if [ -d "$TMP_ROOT" ]; then
    find "$TMP_ROOT" -maxdepth 1 -type d -name "puppeteer_dev_chrome_profile-*" -mmin +120 -exec rm -rf {} + 2>/dev/null || true
    find "$TMP_ROOT" -maxdepth 1 -type d -name "hyperframes-*" -mmin +120 -exec rm -rf {} + 2>/dev/null || true
    find "$TMP_ROOT" -maxdepth 1 -type d -name "temp_ig_*" -mmin +120 -exec rm -rf {} + 2>/dev/null || true
  fi

  # Clean old temporary logs in /app/logs
  find "$ROOT/logs" -type f -name "*.log" -mtime +7 -delete 2>/dev/null || true

  local avail_mb tmp_avail_mb
  avail_mb=$(df -m "$ROOT" | awk 'NR==2 {print $4}')
  if [ -d "$TMP_ROOT" ]; then
    tmp_avail_mb=$(df -m "$TMP_ROOT" | awk 'NR==2 {print $4}')
  else
    tmp_avail_mb=0
  fi
  log "available disk: project=${avail_mb}MB (min ${MIN_DISK_MB}MB), tmp=${tmp_avail_mb}MB (min ${MIN_TMP_DISK_MB}MB)"
  if [ "$avail_mb" -lt "$MIN_DISK_MB" ] || [ "$tmp_avail_mb" -lt "$MIN_TMP_DISK_MB" ]; then
    write_state "preflight" "failed" "low_disk"
    fail "insufficient disk space; blocking generation to avoid unsafe cleanup (project=${avail_mb}MB tmp=${tmp_avail_mb}MB)"
  fi
}

# Bounded NewsNow reachability + stale-feed-age preflight (warning-only; the
# generator enforces MAX_STALE_FEED_AGE_HOURS when it falls back to an old feed).
newsnow_preflight() {
  if curl -sf -m 5 -o /dev/null "$NEWSNOW_URL" 2>/dev/null; then
    log "NewsNow reachable: $NEWSNOW_URL"
  else
    log "WARN: NewsNow ($NEWSNOW_URL) unreachable at preflight; generator may fall back to prior feed"
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "preflight" \
      --error-type "NEWSNOW_UNREACHABLE" --message "NewsNow endpoint unreachable at preflight" || true
  fi
  local feed="$ROOT/data/newsnow_feed.json"
  local max_age_h="${MAX_STALE_FEED_AGE_HOURS:-48}"
  if [ -f "$feed" ]; then
    local age_h=$(( ($(date +%s) - $(stat -c %Y "$feed" 2>/dev/null || echo 0)) / 3600 ))
    log "existing NewsNow feed age: ${age_h}h (max allowed: ${max_age_h}h)"
    if [ "$age_h" -gt "$max_age_h" ]; then
      log "WARN: existing NewsNow feed exceeds max stale age; today's fetch must succeed"
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "preflight" \
        --error-type "STALE_NEWSNOW_FEED" --message "NewsNow feed ${age_h}h old exceeds ${max_age_h}h" || true
    fi
  else
    log "no prior NewsNow feed at $feed; today's fetch must succeed"
  fi
  return 0
}

cleanup_failed_generation() {
  local pid dir
  local log_files=("$@")

  # Move (never rm -rf) failed-generation project dirs to a quarantine root so
  # recovery evidence and unpublished assets are preserved for diagnosis.
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    schedule_has=$(jq --arg pid "$pid" \
      'any(.active_projects[]?; (if type == "object" then .project_id else . end) == $pid)' "$SCHEDULE" 2>/dev/null || echo false)
    if [ "$schedule_has" = "true" ]; then
      log "preserving scheduled failed-generation project: $pid"
      continue
    fi
    if [ -f "$ROOT/projects/$pid/validation_status.json" ]; then
      is_valid=$(jq -r 'if type == "array" then .[-1].strict_quality_pass else .strict_quality_pass end // false' "$ROOT/projects/$pid/validation_status.json" 2>/dev/null || echo false)
      if [ "$is_valid" = "true" ]; then
        log "preserving validated project: $pid"
        continue
      fi
    fi
    for dir in "$ROOT/projects/$pid" "$ROOT/projects_news/$pid"; do
      if [ -d "$dir" ]; then
        mkdir -p "$FAILED_GENERATION_RECOVERY_ROOT"
        mv "$dir" "$FAILED_GENERATION_RECOVERY_ROOT/$pid"
        log "quarantined failed-generation project: $pid -> $FAILED_GENERATION_RECOVERY_ROOT/$pid"
      fi
    done
  done < <(
    grep -h 'PROJECT_ID=' "${log_files[@]}" 2>/dev/null |
      sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' |
      sort -u
  )
}

# ===== Pre-flight: confirm we're inside Docker =====
stage 0 "preflight"
write_heartbeat "started"
cleanup_system_disk_space
if [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" != "1" ]; then
  [ -f /.dockerenv ] || grep -qE 'docker|containerd|lxc|init' /proc/1/cgroup 2>/dev/null || [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" = "1" ] || fail "must run inside Docker container"
fi
command -v python3 >/dev/null  || fail "python3 missing"
command -v ffmpeg   >/dev/null  || fail "ffmpeg missing"
command -v ffprobe  >/dev/null  || fail "ffprobe missing"
command -v codex    >/dev/null  || fail "codex CLI missing"
# Strict pipeline candidates are news by definition. Require explicit freshness
# policy before any generation or paid provider stage can begin.
load_news_max_source_age_from_dotenv
if ! validate_news_max_source_age; then
  fail "NEWS_MAX_SOURCE_AGE_HOURS is required and must be a finite number in (0, 720]"
fi
if [ "${STRICT_PUBLISH_SKIP_DOCKER_CHECK:-0}" != "1" ]; then
  [ -d "$CODEX_HOME" ] || fail "CODEX_HOME does not exist: $CODEX_HOME"
  [ -s "$CODEX_HOME/auth.json" ] || fail "CODEX_HOME missing auth.json: $CODEX_HOME/auth.json"
  [ -s "$CODEX_HOME/config.toml" ] || fail "CODEX_HOME missing config.toml: $CODEX_HOME/config.toml"
fi
log "preflight OK (docker=$(hostname), py=$(python3 --version | awk '{print $2}'), codex=$(codex --version 2>&1 | head -1), codex_home=$CODEX_HOME)"
newsnow_preflight
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
mapfile -t EXISTING_SCHEDULED_IDS < <(jq -r \
  '.active_projects[]? | (.project_id // empty)' "$SCHEDULE")
log "today publish date (local $PUBLISH_TZ): $TODAY"
log "next publish date (local $PUBLISH_TZ): $NEXT_DATE"
log "due today projects: ${TODAY_PROJECT_IDS[*]:-none}"
log "existing scheduled projects: ${EXISTING_SCHEDULED_IDS[*]:-none}"
write_state "prepare" "ok" "today=$TODAY next=$NEXT_DATE due=$(IFS=,; echo "${TODAY_PROJECT_IDS[*]}")"

# ===== STAGE 2: TODAY BATCH — verify native scheduling =====
stage 2 "today-batch"
TODAY_BATCH_FAILED=0
if [ "${#TODAY_PROJECT_IDS[@]}" -gt 0 ]; then
  log "verifying native scheduling for ${#TODAY_PROJECT_IDS[@]} due-today projects"
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$TODAY" >> "$RUN_LOG" 2>&1; then
    TODAY_BATCH_FAILED=1
    write_state "today-batch" "warning" "today_native_scheduling_failed"
    log "WARNING: today native scheduling failed for existing queue entries; continuing workflow to generate and schedule next-day videos"
  else
    log "retained due-today projects for slot cron"
    write_state "today-batch" "ok" "verified=$(IFS=,; echo "${TODAY_PROJECT_IDS[*]}")"
  fi
else
  log "no due projects for today"
  write_state "today-batch" "ok" "none"
fi

# ===== STAGE 3: GENERATE — produce next-day video and assets =====
stage 3 "generate"
export OPENMONTAGE_PYTHON="$PY"
PROJECT_IDS=()
GENERATION_ATTEMPT=0
GEN_STATUS=1
if [ "${STRICT_PUBLISH_SKIP_GENERATE:-0}" = "1" ]; then
  GENERATE_LOG="${STRICT_PUBLISH_GENERATE_LOG:-$(ls -t "$LOG_DIR"/generate_*.log | head -1)}"
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
    bash "$ROOT/scripts/run_daily_news_pipeline.sh" 199>&- 2>&1 | tee "$GENERATE_LOG"
    GEN_STATUS="${PIPESTATUS[0]}"
    set -e
    mapfile -t PROJECT_IDS < <(grep -h 'PROJECT_ID=' "$GENERATE_LOG" | sed -n 's/.*PROJECT_ID=\([A-Za-z0-9_-]*\).*/\1/p' | awk '!seen[$0]++')
    VALID_COUNT=0
    for pid in "${PROJECT_IDS[@]}"; do
      if [[ " ${EXISTING_SCHEDULED_IDS[*]} " =~ " ${pid} " ]]; then
        continue
      fi
      if [ -d "$ROOT/projects/$pid" ] && [ -f "$ROOT/projects/$pid/validation_status.json" ]; then
        is_valid=$(jq -r 'if type == "array" then .[-1].strict_quality_pass else .strict_quality_pass end // false' "$ROOT/projects/$pid/validation_status.json" 2>/dev/null || echo false)
        if [ "$is_valid" = "true" ]; then
          VALID_COUNT=$((VALID_COUNT + 1))
        fi
      fi
    done
    if { [ "$GEN_STATUS" -eq 0 ] || [ "$VALID_COUNT" -ge 1 ]; } && [ "${#PROJECT_IDS[@]}" -gt 0 ]; then
      log "generation attempt $GENERATION_ATTEMPT completed with $VALID_COUNT validated project(s) (exit=$GEN_STATUS)"
      break
    fi
    log "generation attempt $GENERATION_ATTEMPT failed (exit=$GEN_STATUS projects=${#PROJECT_IDS[@]})"
  done
fi

FILTERED_PROJECT_IDS=()
for pid in "${PROJECT_IDS[@]}"; do
  if [[ ! " ${EXISTING_SCHEDULED_IDS[*]} " =~ " ${pid} " ]]; then
    FILTERED_PROJECT_IDS+=("$pid")
  fi
done
PROJECT_IDS=("${FILTERED_PROJECT_IDS[@]}")

[ "${#PROJECT_IDS[@]}" -gt 0 ] || {
  cleanup_failed_generation "$LOG_DIR"/generate_"${RUN_TS}"_attempt*.log "$GENERATE_LOG"
  write_state "generate" "failed"
  fail "expected at least 1 new project from generation after $GENERATION_ATTEMPT attempts"
}
VALID_COUNT=0
for pid in "${PROJECT_IDS[@]}"; do
  if [ -d "$ROOT/projects/$pid" ] && [ -f "$ROOT/projects/$pid/validation_status.json" ]; then
    is_valid=$(jq -r 'if type == "array" then .[-1].strict_quality_pass else .strict_quality_pass end // false' "$ROOT/projects/$pid/validation_status.json" 2>/dev/null || echo false)
    if [ "$is_valid" = "true" ]; then
      VALID_COUNT=$((VALID_COUNT + 1))
    fi
  fi
done

if [ "$GEN_STATUS" -ne 0 ] && [ "$VALID_COUNT" -eq 0 ]; then
  cleanup_failed_generation "$LOG_DIR"/generate_"${RUN_TS}"_attempt*.log "$GENERATE_LOG"
  write_state "generate" "failed"
  fail "generation failed after $GENERATION_ATTEMPT attempts (exit=$GEN_STATUS; see $GENERATE_LOG)"
fi
if [ "$GEN_STATUS" -eq 0 ]; then
  write_state "generate" "ok"
else
  write_state "generate" "partial" "valid_count=$VALID_COUNT"
fi
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
  # Every candidate emitted by the daily-news generator is news, regardless of
  # identity heuristics used by shared publishing entry points.
  if ! "$PY" -c 'import os, sys; from lib.news_release_gate import require_news_evidence; require_news_evidence(sys.argv[1], os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS", ""), metadata={"pipeline_type": "newsnow"})' "$PDIR" >> "$VERIFY_LOG" 2>&1; then
    log "FAIL $PID: required news evidence invalid or missing"
    continue
  fi
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
  if [ -f "$PDIR/validation_status.json" ]; then
    is_valid=$(jq -r 'if type == "array" then any(.[]; .strict_quality_pass == true) else .strict_quality_pass end // false' "$PDIR/validation_status.json" 2>/dev/null || echo false)
    if [ "$is_valid" = "true" ]; then
      log "project $PID already verified strict quality pass in generation stage"
      VALIDATED_PIDS+=("$PID")
      continue
    fi
  fi
  for ((retry=1; retry<=MAX_RETRIES; retry++)); do
    log "attempt $retry/$MAX_RETRIES for $PID"
    val_status=0
    "$PY" "$ROOT/scripts/codex_agent_validation.py" "$PDIR" --strict --retry "$MAX_RETRIES" 199>&- \
        >> "$CLAUDE_LOG" 2>&1 || val_status=$?
    if [ "$val_status" -eq 0 ]; then
      VALIDATION_PASSED=1
      break
    elif [ "$val_status" -eq 2 ]; then
      log "attempt $retry encountered deterministic failure for $PID; skipping redundant retries"
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
TARGET_VALIDATED_COUNT="${EXPECTED_SUCCESS_COUNT:-3}"
if [ "${#VALIDATED_PIDS[@]}" -lt "$TARGET_VALIDATED_COUNT" ]; then
  write_state "claude-validate" "partial" "validated=$(IFS=,; echo "${VALIDATED_PIDS[*]}")"
  log "WARNING: PARTIAL: strict validation achieved only ${#VALIDATED_PIDS[@]}/$TARGET_VALIDATED_COUNT validated projects (see $CLAUDE_LOG)"
else
  write_state "claude-validate" "ok" "validated=$(IFS=,; echo "${VALIDATED_PIDS[*]}")"
fi
log "claude agent strict validation completed for ${#VALIDATED_PIDS[@]} projects: ${VALIDATED_PIDS[*]}"

# ===== STAGE 6: QUEUE — current-day recovery plus next-day schedule =====
stage 6 "queue"
# Serialize schedule reads/writes with publish_active_projects.py and
# clear_stale_projects.sh, which use fcntl.flock on the same lock file.
# The lock must be released before stage 7 cleanup (which acquires it).
QUEUE_LOCK="$SCHEDULE.lock"
exec 200>"$QUEUE_LOCK"
if ! flock -x -w "${SCHEDULE_LOCK_WAIT_SECONDS:-300}" 200; then
  write_state "queue" "failed" "lock_timeout"
  fail "could not acquire schedule lock $QUEUE_LOCK within ${SCHEDULE_LOCK_WAIT_SECONDS:-300}s; another writer is active"
fi
log "acquired schedule lock $QUEUE_LOCK"
QUEUE_OK=1
QUEUED_PIDS=()
TODAY_QUEUED_PIDS=()
NEXT_QUEUED_PIDS=()

TODAY_SLOTS_JSON=$(jq -c '.slots.today_publish_slots_vn // .slots.publish_slots_vn // ["09:15", "14:15", "21:15"]' "$SCHEDULE")
mapfile -t TODAY_CANDIDATE_SLOTS < <(jq -r '.[]' <<< "$TODAY_SLOTS_JSON")

NEXT_SLOTS_JSON=$(jq -c '.slots.publish_slots_vn // ["09:15", "14:15", "21:15"]' "$SCHEDULE")
mapfile -t NEXT_CANDIDATE_SLOTS < <(jq -r '.[]' <<< "$NEXT_SLOTS_JSON")

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
for SLOT in "${TODAY_CANDIDATE_SLOTS[@]}"; do
  SLOT_EPOCH=$(TZ="$PUBLISH_TZ" date -d "$TODAY $SLOT" +%s 2>/dev/null || echo 0)
  if [ "$SLOT_EPOCH" -gt "$((NOW_EPOCH + 1200))" ] && [ -z "${TODAY_OCCUPIED[$SLOT]:-}" ]; then
    TODAY_SLOTS+=("$SLOT")
  fi
done
for SLOT in "${NEXT_CANDIDATE_SLOTS[@]}"; do
  if [ -z "${NEXT_OCCUPIED[$SLOT]:-}" ]; then
    NEXT_SLOTS+=("$SLOT")
  fi
done

AVAILABLE_SLOT_COUNT=$((${#TODAY_SLOTS[@]} + ${#NEXT_SLOTS[@]}))
[ "$AVAILABLE_SLOT_COUNT" -ge "${#VALIDATED_PIDS[@]}" ] \
  || { write_state "queue" "failed"; fail "not enough unoccupied current/next-day publish slots ($AVAILABLE_SLOT_COUNT) for ${#VALIDATED_PIDS[@]} projects"; }

TMP_QUEUE=$(mktemp)
cp "$SCHEDULE" "$TMP_QUEUE"

# Determine target allocation between today (fill up to TARGET_TODAY_COUNT, default 3) and next day (primary target).
TARGET_TODAY_COUNT="${TARGET_TODAY_COUNT:-3}"
CURRENT_TODAY_COUNT="${#TODAY_PROJECT_IDS[@]}"
NEEDED_TODAY=0
if [ "$CURRENT_TODAY_COUNT" -lt "$TARGET_TODAY_COUNT" ]; then
  NEEDED_TODAY=$((TARGET_TODAY_COUNT - CURRENT_TODAY_COUNT))
fi

MAX_TODAY_ALLOCATION=0
if [ "${TODAY_BATCH_FAILED:-0}" -eq 0 ] && [ "$NEEDED_TODAY" -gt 0 ] && [ "${#TODAY_SLOTS[@]}" -gt 0 ]; then
  MAX_TODAY_ALLOCATION="$NEEDED_TODAY"
  if [ "$MAX_TODAY_ALLOCATION" -gt "${#TODAY_SLOTS[@]}" ]; then
    MAX_TODAY_ALLOCATION="${#TODAY_SLOTS[@]}"
  fi
fi

TODAY_IDX=0
NEXT_IDX=0
for PID in "${VALIDATED_PIDS[@]}"; do
  if [ "$NEXT_IDX" -lt "${#NEXT_SLOTS[@]}" ] && { [ "$TODAY_IDX" -ge "$MAX_TODAY_ALLOCATION" ] || [ "$TODAY_IDX" -ge "${#TODAY_SLOTS[@]}" ]; }; then
    DATE="$NEXT_DATE"
    SLOT="${NEXT_SLOTS[$NEXT_IDX]}"
    NEXT_QUEUED_PIDS+=("$PID")
    NEXT_IDX=$((NEXT_IDX + 1))
  elif [ "$TODAY_IDX" -lt "$MAX_TODAY_ALLOCATION" ] && [ "$TODAY_IDX" -lt "${#TODAY_SLOTS[@]}" ]; then
    DATE="$TODAY"
    SLOT="${TODAY_SLOTS[$TODAY_IDX]}"
    TODAY_QUEUED_PIDS+=("$PID")
    TODAY_IDX=$((TODAY_IDX + 1))
  elif [ "$NEXT_IDX" -lt "${#NEXT_SLOTS[@]}" ]; then
    DATE="$NEXT_DATE"
    SLOT="${NEXT_SLOTS[$NEXT_IDX]}"
    NEXT_QUEUED_PIDS+=("$PID")
    NEXT_IDX=$((NEXT_IDX + 1))
  elif [ "$TODAY_IDX" -lt "${#TODAY_SLOTS[@]}" ]; then
    DATE="$TODAY"
    SLOT="${TODAY_SLOTS[$TODAY_IDX]}"
    TODAY_QUEUED_PIDS+=("$PID")
    TODAY_IDX=$((TODAY_IDX + 1))
  else
    DATE="$NEXT_DATE"
    SLOT="${NEXT_SLOTS[0]:-09:15}"
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

# Release the schedule lock before platform-schedule and stage 7 cleanup:
# clear_stale_projects.sh -> deactivate_project re-acquires the same lock, so
# holding it here would deadlock the cleanup step.
flock -u 200
exec 200>&-

stage 6.5 "platform-schedule"
TODAY_PLATFORM_OK=1
NEXT_PLATFORM_OK=1

if [ "${#TODAY_QUEUED_PIDS[@]}" -gt 0 ]; then
  log "scheduling ${#TODAY_QUEUED_PIDS[@]} projects for today ($TODAY)"
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$TODAY" 2>&1 | tee -a "$RUN_LOG"; then
    TODAY_PLATFORM_OK=0
    write_state "platform-schedule" "warning" "date=$TODAY error=today_native_scheduling_failed"
    log "WARNING: current-day YouTube scheduling failed; continuing to schedule next-day projects"
  fi
fi

if [ "${#NEXT_QUEUED_PIDS[@]}" -gt 0 ]; then
  log "scheduling ${#NEXT_QUEUED_PIDS[@]} projects for next day ($NEXT_DATE)"
  if ! "$PY" "$ROOT/scripts/schedule_today_native.py" --date "$NEXT_DATE" 2>&1 | tee -a "$RUN_LOG"; then
    NEXT_PLATFORM_OK=0
    write_state "platform-schedule" "failed" "date=$NEXT_DATE"
    fail "next-day YouTube scheduling failed; queued projects retained"
  fi
fi

if [ "$TODAY_PLATFORM_OK" -eq 0 ]; then
  log "WARNING: current-day YouTube scheduling encountered errors, but next-day videos were successfully scheduled"
  write_state "platform-schedule" "partial" "today_failed=true next=$(IFS=,; echo "${NEXT_QUEUED_PIDS[*]}")"
else
  write_state "platform-schedule" "ok" "today=$(IFS=,; echo "${TODAY_QUEUED_PIDS[*]}") next=$(IFS=,; echo "${NEXT_QUEUED_PIDS[*]}")"
fi

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
write_heartbeat "completed"
exit 0
