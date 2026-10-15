#!/usr/bin/env bash
# Daily AI news video generation pipeline.
# Selects trending topic, runs directors pipeline, generates Vietnamese video (120s + 60s Reels), updates publish_schedule.json.
set -euo pipefail
REHEARSAL_MANIFEST=""
EXISTING_PROJECT_IDS=""
if [ "${1:-}" = "--rehearsal-bundle" ]; then
  [ "$#" -eq 2 ] && [ -n "$2" ] || {
    echo "Usage: $0 [--rehearsal-bundle NONEMPTY_MANIFEST] [--project-ids PROJECT_ID[,PROJECT_ID...]]" >&2
    exit 2
  }
  REHEARSAL_MANIFEST="$2"
elif [ "${1:-}" = "--project-ids" ]; then
  [ "$#" -eq 2 ] && [ -n "$2" ] || {
    echo "Usage: $0 [--rehearsal-bundle NONEMPTY_MANIFEST] [--project-ids PROJECT_ID[,PROJECT_ID...]]" >&2
    exit 2
  }
  EXISTING_PROJECT_IDS="$2"
elif [ "$#" -ne 0 ]; then
  echo "Usage: $0 [--rehearsal-bundle MANIFEST] [--project-ids PROJECT_ID[,PROJECT_ID...]]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REHEARSAL_TERMINAL_STAGE="preflight"
REHEARSAL_SUCCESSFUL_IDS=()
REHEARSAL_IDS_FILE=""
write_rehearsal_report_on_exit() {
  local original_status=$?
  trap - EXIT
  if [ -n "${REHEARSAL_IDS_FILE:-}" ]; then rm -f "$REHEARSAL_IDS_FILE"; fi
  if [ -n "$REHEARSAL_MANIFEST" ]; then
    python3 "$ROOT/scripts/write_daily_news_rehearsal_report.py" \
      --root "$ROOT" --manifest "$REHEARSAL_MANIFEST" \
      --exit-status "$original_status" --terminal-stage "$REHEARSAL_TERMINAL_STAGE" \
      --successful-ids "$(IFS=,; printf '%s' "${REHEARSAL_SUCCESSFUL_IDS[*]:-}")" || true
  fi
  exit "$original_status"
}
if [ -n "$REHEARSAL_MANIFEST" ]; then
  trap write_rehearsal_report_on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
fi

# This gate runs before .env, logs, network clients, credentials, or tools.
# The staging checkout must carry an explicit durable test-only marker.
if [ -n "$REHEARSAL_MANIFEST" ]; then
  [ -z "${PRODUCTION_RELEASE:-}" ] && [ -z "${STRICT_PRODUCTION:-}" ] || {
    echo "ERROR: rehearsal mode is forbidden in production environments" >&2; exit 2;
  }
  [ -n "${NEWS_MAX_SOURCE_AGE_HOURS:-}" ] || {
    echo "ERROR: NEWS_MAX_SOURCE_AGE_HOURS must be explicitly set for rehearsal" >&2; exit 2;
  }
  python3 -c 'import math,sys; v=float(sys.argv[1]); sys.exit(0 if math.isfinite(v) and 0 < v <= 720 else 1)' \
    "$NEWS_MAX_SOURCE_AGE_HOURS" 2>/dev/null || {
      echo "ERROR: NEWS_MAX_SOURCE_AGE_HOURS must be finite and in (0, 720]" >&2; exit 2;
    }
  REHEARSAL_IDS_FILE="$(mktemp)"
  python3 "$ROOT/scripts/prepare_daily_news_rehearsal.py" \
    --manifest "$REHEARSAL_MANIFEST" --root "$ROOT" \
    --max-source-age-hours "$NEWS_MAX_SOURCE_AGE_HOURS" > "$REHEARSAL_IDS_FILE" || exit $?
  mapfile -t REHEARSAL_PROJECT_IDS < "$REHEARSAL_IDS_FILE"
  REHEARSAL_TERMINAL_STAGE="frozen_inputs_staged"
fi

mkdir -p "$ROOT/logs"

if [ -z "$REHEARSAL_MANIFEST" ] && [ -f .env ]; then
  set -a; . ./.env; set +a
fi

export PATH="/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$ROOT"
export PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"
# Templated news path: when 1, projects must carry a template selection +
# typed content instance and compositions are materialized deterministically
# from the approved package (no free-form HTML, no repair/sed mutation).
# Development-only; production activation is a separate explicit approval.
NEWS_TEMPLATE_MODE="${NEWS_TEMPLATE_MODE:-0}"

FFPROBE_BIN="$(command -v ffprobe || true)"
FFMPEG_BIN="$(command -v ffmpeg || true)"
if [ -z "$FFPROBE_BIN" ]; then FFPROBE_BIN="$(find "$HOME/.local/share/uv" -name ffprobe -type f -executable 2>/dev/null | head -1)"; fi
if [ -z "$FFMPEG_BIN" ]; then FFMPEG_BIN="$(find "$HOME/.local/share/uv" -name ffmpeg -type f -executable 2>/dev/null | head -1)"; fi
HYPERFRAMES_BIN="$(command -v hyperframes || true)"
if [ -z "$HYPERFRAMES_BIN" ] && [ -x "$ROOT/node_modules/.bin/hyperframes" ]; then HYPERFRAMES_BIN="$ROOT/node_modules/.bin/hyperframes"; fi
if [ -z "$HYPERFRAMES_BIN" ]; then HYPERFRAMES_BIN="$(find "$HOME/.npm/_npx" -path '*/node_modules/.bin/hyperframes' -type f -perm -111 2>/dev/null | sort | tail -1)"; fi
[ -n "$FFPROBE_BIN" ] || { echo "ERROR: ffprobe is required" >&2; exit 1; }
[ -n "$FFMPEG_BIN" ] || { echo "ERROR: ffmpeg is required for content QA" >&2; exit 1; }
[ -n "$HYPERFRAMES_BIN" ] || { echo "ERROR: hyperframes CLI is required" >&2; exit 1; }

# Export FFMPEG bin directory to PATH so hyperframes CLI can invoke it
FFMPEG_DIR="$(dirname "$FFMPEG_BIN")"
export PATH="$FFMPEG_DIR:$PATH"

if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi
if [ -n "$REHEARSAL_MANIFEST" ]; then
  NEWS_TEMPLATE_MODE=0
fi

# NEWS_EVIDENCE_GATE_FUNCTIONS_BEGIN
validate_news_generation_config() {
  if [ -z "${NEWS_MAX_SOURCE_AGE_HOURS:-}" ]; then
    echo "ERROR: NEWS_MAX_SOURCE_AGE_HOURS must be explicitly configured in (0, 720] hours" >&2
    return 1
  fi
  "$PY" -c 'import math,sys; value=float(sys.argv[1]); sys.exit(0 if math.isfinite(value) and 0 < value <= 720 else 1)' \
    "$NEWS_MAX_SOURCE_AGE_HOURS" || {
      echo "ERROR: NEWS_MAX_SOURCE_AGE_HOURS must be finite and in (0, 720]" >&2
      return 1
    }
}

validate_project_news_evidence() {
  local project_dir="$1" validation_log="$2"
  if "$PY" "$ROOT/scripts/validate_news_evidence.py" "$project_dir" \
      --max-source-age-hours "$NEWS_MAX_SOURCE_AGE_HOURS" >"$validation_log" 2>&1; then
    return 0
  fi
  echo "ERROR: news evidence validation failed for $project_dir; see $validation_log" >&2
  return 1
}
# NEWS_EVIDENCE_GATE_FUNCTIONS_END

if ! validate_news_generation_config; then
  exit 1
fi

"$PY" -c 'from scripts.publish_config import load_config; load_config()' || {
  echo "ERROR: invalid publish timezone configuration" >&2
  exit 1
}

# Rehearsal inputs are frozen, copied, and marked test-only by the preflight helper.
# Never execute acquisition/production selectors in this branch.
if [ -n "$REHEARSAL_MANIFEST" ]; then
  REHEARSAL_TERMINAL_STAGE="directors_and_validation"
  FEED_STALE=0
  PROJECT_IDS=("${REHEARSAL_PROJECT_IDS[@]}")
  export OPENMONTAGE_REHEARSAL=1
elif [ -n "$EXISTING_PROJECT_IDS" ]; then
  REHEARSAL_TERMINAL_STAGE="directors_and_validation"
  FEED_STALE=0
  IFS=',' read -r -a PROJECT_IDS <<< "$EXISTING_PROJECT_IDS"
  EXPECTED_SUCCESS_COUNT="${#PROJECT_IDS[@]}"
  for PROJECT_ID in "${PROJECT_IDS[@]}"; do
    if ! [[ "$PROJECT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$ ]]; then
      echo "[$(date -u +%FT%TZ)] ERROR: invalid project id: $PROJECT_ID" >&2
      exit 2
    fi
    PROJECT_DIR="$ROOT/projects/$PROJECT_ID"
    if ! "$PY" -S -c 'import pathlib,sys
try:
    root = pathlib.Path(sys.argv[1]).resolve(strict=True)
    project = pathlib.Path(sys.argv[2])
    if project.is_symlink() or (project / "artifacts").is_symlink():
        raise SystemExit(1)
    resolved = project.resolve(strict=True)
except OSError:
    raise SystemExit(1)
raise SystemExit(0 if resolved.is_dir() and resolved.is_relative_to(root) else 1)' "$ROOT/projects" "$PROJECT_DIR"; then
      echo "[$(date -u +%FT%TZ)] ERROR: existing project path is invalid or unsafe: $PROJECT_ID" >&2
      exit 2
    fi
    if [ ! -s "$PROJECT_DIR/artifacts/research_brief.json" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: existing project missing research brief: $PROJECT_ID" >&2
      exit 2
    fi
    if [ ! -s "$PROJECT_DIR/artifacts/news_evidence.json" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: existing project missing reviewed news evidence: $PROJECT_ID" >&2
      exit 2
    fi
    if ! validate_project_news_evidence "$PROJECT_DIR" "$ROOT/logs/news_evidence_${PROJECT_ID}_resume.log"; then
      exit 2
    fi
  done
else
# Step 0: Fetch current NewsNow sources with stale fallback.
FEED_STALE=0
NEWSNOW_URL="${NEWSNOW_API_URL:-http://127.0.0.1:4444}"
if ! "$PY" tools/news/news_pipeline_cli.py fetch --url "$NEWSNOW_URL" --output data/newsnow_feed.json --min-items 3; then
  if [ ! -f data/newsnow_feed.json ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: NewsNow fetch failed and no prior feed exists."
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "news_fetch" \
      --error-type "NEWSNOW_FETCH_FAILED" --message "NewsNow fetch failed and no prior feed exists" || true
    exit 1
  fi
  FEED_STALE=1
  echo "[$(date -u +%FT%TZ)] WARN: NewsNow fetch failed; using existing feed."
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-retry --stage "news_fetch" \
    --reason "NewsNow fetch failed, using fallback feed" --attempt 1 --max-attempts 1 || true

  # Enforce an acceptable stale-feed age on the fallback path. A very old feed
  # produces stale news content, so fail closed rather than generate from it.
  MAX_STALE_FEED_AGE_HOURS="${MAX_STALE_FEED_AGE_HOURS:-48}"
  FEED_FILE="$ROOT/data/newsnow_feed.json"
  if [ -f "$FEED_FILE" ]; then
    FEED_MTIME="$(stat -c %Y "$FEED_FILE" 2>/dev/null || echo 0)"
    FEED_AGE_H=$(( ( $(date +%s) - FEED_MTIME ) / 3600 ))
    if [ "$FEED_AGE_H" -gt "$MAX_STALE_FEED_AGE_HOURS" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: fallback NewsNow feed is ${FEED_AGE_H}h old (max ${MAX_STALE_FEED_AGE_HOURS}h); refusing to generate from stale feed."
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "news_fetch" \
        --error-type "STALE_NEWSNOW_FEED" --message "fallback NewsNow feed ${FEED_AGE_H}h old exceeds max ${MAX_STALE_FEED_AGE_HOURS}h" || true
      exit 1
    fi
  fi
fi

# Step 1: Select and initialize distinct current topics. Preserve the producer's
# exit status across tee so partial output cannot make a failed acquisition look
# like a successful generation attempt.
# PRODUCER_EXECUTION_BEGIN
PRODUCE_LOG="$(mktemp "$ROOT/logs/news_produce_XXXXXXXX.log")"
set +e
"$PY" tools/news/news_pipeline_cli.py produce --input data/newsnow_feed.json --count 6 2>&1 | tee "$PRODUCE_LOG"
PRODUCER_PIPE_STATUS=("${PIPESTATUS[@]}")
set -e
PRODUCE_STATUS="${PRODUCER_PIPE_STATUS[0]}"
TEE_STATUS="${PRODUCER_PIPE_STATUS[1]}"
if [ "$PRODUCE_STATUS" -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: topic production failed (exit=$PRODUCE_STATUS); refusing partial candidate output." >&2
  exit "$PRODUCE_STATUS"
fi
if [ "$TEE_STATUS" -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: could not persist topic production log (exit=$TEE_STATUS)." >&2
  exit "$TEE_STATUS"
fi
if ! PROJECT_ID_OUTPUT="$(awk '/^PROJECT_ID=[A-Za-z0-9_-]+$/ {
  id = substr($0, 12)
  if (length(id) <= 128 && !seen[id]++ && id != "_failed_generation_recovered" && index(id, "_failed_generation_recovered_") != 1) print id
}' "$PRODUCE_LOG")"; then
  echo "ERROR: could not parse topic production log: $PRODUCE_LOG" >&2
  exit 1
fi
PROJECT_IDS=()
if [ -n "$PROJECT_ID_OUTPUT" ]; then
  mapfile -t PROJECT_IDS <<< "$PROJECT_ID_OUTPUT"
fi
# PRODUCER_EXECUTION_END
if [ "${#PROJECT_IDS[@]}" -lt 3 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: Expected at least three initialized projects, got ${#PROJECT_IDS[@]}."
  exit 1
fi
fi

SUCCESSFUL_COUNT=0
EXPECTED_SUCCESS_COUNT="${EXPECTED_SUCCESS_COUNT:-3}"

for PROJECT_ID in "${PROJECT_IDS[@]}"; do
  REHEARSAL_TERMINAL_STAGE="project:${PROJECT_ID}:directors_and_validation"
  cd "$ROOT"
  PROJECT_DIR="$ROOT/projects/$PROJECT_ID"
  if [ -d "$PROJECT_DIR" ] && [ -z "$REHEARSAL_MANIFEST" ]; then
    chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true
  fi
  mkdir -p "$PROJECT_DIR/artifacts" "$PROJECT_DIR/hyperframes" "$PROJECT_DIR/hyperframes_reels"
  if [ -z "$REHEARSAL_MANIFEST" ]; then chmod -R 777 "$PROJECT_DIR" 2>/dev/null || true; fi
  echo "[$(date -u +%FT%TZ)] PROJECT_ID=$PROJECT_ID"

# Step 2.5: Run Directors pipeline via Codex CLI (unattended, logged) (P2)
DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"
START_TS=$(date -u +%s)

echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"

DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_result.json"

set +e
DIRECTORS_TIMEOUT_SECONDS="${DIRECTORS_TIMEOUT_SECONDS:-3600}"
DIRECTORS_MAX_BUDGET_USD="${DIRECTORS_MAX_BUDGET_USD:-40}"
PROMPT_DIR="$ROOT/scripts/prompts"
render_director_prompt() {
  local template="$1"
  [ -f "$template" ] || { echo "ERROR: template file not found: $template" >&2; return 1; }
  [ -s "$template" ] || { echo "ERROR: template file is empty: $template" >&2; return 1; }
  local result
  result="$(sed "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" "$template")"

  if [ -z "${result:-}" ] || [ "$result" = "$(cat "$template" 2>/dev/null)" ]; then
    echo "ERROR: template interpolation failed or untouched: $template" >&2
    return 1
  fi
  printf '%s\n' "$result"
}
if [ -n "$REHEARSAL_MANIFEST" ]; then
  PROMPT_STR=""
  DIRECTOR_SYSTEM_NOTE=""
else
  PROMPT_STR="$(render_director_prompt "$PROMPT_DIR/director_generate.prompt.md")" || {
    echo "[$(date -u +%FT%TZ)] ERROR: missing/invalid director generation prompt" >> "$DIRECTORS_LOG"
    exit 1
  }
  DIRECTOR_SYSTEM_NOTE="$(render_director_prompt "$PROMPT_DIR/director_system.prompt.md")" || {
    echo "[$(date -u +%FT%TZ)] ERROR: missing/invalid director system prompt" >> "$DIRECTORS_LOG"
    exit 1
  }
fi
DIRECTOR_FULL_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes/index.html"
DIRECTOR_REELS_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes_reels/index.html"
DIRECTOR_ARTIFACTS_READY=0
# Existing files are not a valid success signal: they may belong to a prior run.
# A director timeout must fail closed rather than publishing stale content.

run_directors() {
  if [ -n "$REHEARSAL_MANIFEST" ]; then
    echo "ERROR: director invocation is disabled in rehearsal mode" >&2
    return 125
  fi
  local prompt="${1:-$PROMPT_STR}"
  local session_id="${2:-}"
  local resume_flag=""
  if [ -n "$session_id" ] && [ "$session_id" != "?" ] && [ "$session_id" != "null" ]; then
    resume_flag="--resume $session_id"
  fi
  if [ "$(id -u)" -eq 0 ]; then
    export PROMPT_STR="$prompt"
    export DIRECTOR_SYSTEM_NOTE
    export ROOT
    export DIRECTORS_TIMEOUT_SECONDS
    export DIRECTORS_MAX_BUDGET_USD="${DIRECTORS_MAX_BUDGET_USD:-20}"
    export RESUME_FLAG="$resume_flag"
    export PROJECT_DIR="$PROJECT_DIR"
    CODEX_BIN="$(command -v codex || true)"
    if [ -z "$CODEX_BIN" ]; then
      for c in /usr/local/bin/codex /usr/bin/codex "$HOME/.local/bin/codex"; do
        if [ -x "$c" ]; then CODEX_BIN="$c"; break; fi
      done
    fi
    if [ -n "$CODEX_BIN" ]; then
      export CODEX_BIN
      if id node >/dev/null 2>&1; then
        su node -p -s /bin/bash -c '
        export PATH="$PATH"; export HOME="/home/node"
        export PYTHONPATH="$PYTHONPATH"
        export CODEX_HOME="/home/node/.codex_pipeline"
        mkdir -p "$CODEX_HOME"
        export CODEX_MODEL="${CODEX_MODEL:-model-medium-hight}"
        if [ -s "$CODEX_HOME/auth.json" ]; then
          export OPENAI_API_KEY="$(jq -r .OPENAI_API_KEY "$CODEX_HOME/auth.json" 2>/dev/null || true)"
        fi
        cd "$PROJECT_DIR"
        test -s "artifacts/research_brief.json" || exit 7
        timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json --config "model=\"$CODEX_MODEL\"" "$PROMPT_STR" < /dev/null
      '
      fi
    else
      echo "[$(date -u +%FT%TZ)] ERROR: codex CLI not found, cannot run directors" >&2
      return 1
    fi
  else
    cd "$PROJECT_DIR"
    CODEX_BIN="$(command -v codex || true)"
    if [ -z "$CODEX_BIN" ]; then
      for c in /usr/local/bin/codex /usr/bin/codex "$HOME/.local/bin/codex"; do
        if [ -x "$c" ]; then CODEX_BIN="$c"; break; fi
      done
    fi
    if [ -n "$CODEX_BIN" ]; then
      export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
      mkdir -p "$CODEX_HOME"
      export CODEX_MODEL="${CODEX_MODEL:-model-medium-hight}"
      timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json --config "model=\"$CODEX_MODEL\"" "$prompt" < /dev/null
    else
      echo "[$(date -u +%FT%TZ)] ERROR: codex CLI not found, cannot run directors" >&2
    fi
  fi
}

DIRECTOR_ARTIFACT_FALLBACK=0
if [ -n "$REHEARSAL_MANIFEST" ]; then
  cp "$PROJECT_DIR/artifacts/director_reply.json" "$DIRECTORS_JSON"
  DIRECTOR_EXIT=0
  DIRECTOR_ARTIFACT_FALLBACK=1
else
  if ! command -v timeout >/dev/null 2>&1; then
    echo "[$(date -u +%FT%TZ)] ERROR: timeout command is required for directors" >> "$DIRECTORS_LOG"
    exit 1
  fi
  DIRECTOR_ATTEMPT_START_NS="$("$PY" -c 'import time; print(time.time_ns())')" || exit 1
  run_directors > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
  DIRECTOR_EXIT=$?
fi
if [ "$DIRECTOR_EXIT" -eq 124 ] && [ "$DIRECTOR_ARTIFACTS_READY" -eq 1 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: directors timed out; refusing stale artifacts" >> "$DIRECTORS_LOG"
fi

# Flatten any director-created subdirectory nesting so compositions land at canonical paths.
for nested in "$PROJECT_DIR"/hyperframes/*/index.html; do
  [ -f "$nested" ] && mv "$nested" "$PROJECT_DIR/hyperframes/index.html" && rmdir "$(dirname "$nested")" 2>/dev/null || true
done
for nested in "$PROJECT_DIR"/hyperframes_reels/*/index.html; do
  [ -f "$nested" ] && mv "$nested" "$PROJECT_DIR/hyperframes_reels/index.html" && rmdir "$(dirname "$nested")" 2>/dev/null || true
done

if [ -s "$PROJECT_DIR/hyperframes/index.html" ] && [ ! -s "$PROJECT_DIR/hyperframes_reels/index.html" ]; then
    mkdir -p "$PROJECT_DIR/hyperframes_reels"
    cp "$PROJECT_DIR/hyperframes/index.html" "$PROJECT_DIR/hyperframes_reels/index.html" || true
fi
if [ -s "$PROJECT_DIR/hyperframes_reels/index.html" ] && [ ! -s "$PROJECT_DIR/hyperframes/index.html" ]; then
    mkdir -p "$PROJECT_DIR/hyperframes"
    cp "$PROJECT_DIR/hyperframes_reels/index.html" "$PROJECT_DIR/hyperframes/index.html" || true
fi

# ---- Templated path: materialize deterministic compositions from a typed
# content instance. In templated mode the director emits
# artifacts/template_selection.json (template_id/template_version) and
# artifacts/template_content.json (a schema-valid content instance) instead
# of free-form HTML. The materializer produces byte-stable compositions and
# records template_provenance.json. Free-form HTML, repair, and sed mutation
# are bypassed so the provenance hashes stay intact. Production activation
# remains blocked on catalog review_status == "approved" (enforced by the
# scheduler provenance gate in schedule_today_native.py). ----
TEMPLATE_MODE=0
TEMPLATE_PACKAGE=""
TEMPLATE_VERSION=""
CONTENT_INSTANCE=""
MATERIALIZE_EXIT=0
if [ "$NEWS_TEMPLATE_MODE" = "1" ]; then
  sel="$PROJECT_DIR/artifacts/template_selection.json"
  cnt="$PROJECT_DIR/artifacts/template_content.json"
  if [ -s "$sel" ] && [ -s "$cnt" ]; then
    TEMPLATE_MODE=1
    TEMPLATE_PACKAGE="$(jq -r '.template_id // empty' "$sel" 2>/dev/null)"
    TEMPLATE_VERSION="$(jq -r '.template_version // empty' "$sel" 2>/dev/null)"
    CONTENT_INSTANCE="$cnt"
    if [ -z "$TEMPLATE_PACKAGE" ]; then
      echo "[$(date -u +%FT%TZ)] FATAL type=templated_no_package project=$PROJECT_ID" >&2
      continue
    fi
    echo "[$(date -u +%FT%TZ)] TEMPLATE_MODE project=$PROJECT_ID package=$TEMPLATE_PACKAGE version=$TEMPLATE_VERSION" \
      >> "$ROOT/logs/directors_${PROJECT_ID}.log"
    if [ "$DIRECTOR_EXIT" -ne 0 ]; then
      echo "[$(date -u +%FT%TZ)] WARN: director failed with exit=$DIRECTOR_EXIT; rejecting candidate despite template selection" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      MATERIALIZE_EXIT="$DIRECTOR_EXIT"
    elif "$PY" "$ROOT/scripts/materialize_news_template.py" \
        --package "$TEMPLATE_PACKAGE" \
        --content "$CONTENT_INSTANCE" \
        --project-dir "$ROOT/projects/$PROJECT_ID" \
        --variant both > "$ROOT/logs/materializer_${PROJECT_ID}.json" 2>> "$ROOT/logs/directors_${PROJECT_ID}.log"; then
      MATERIALIZE_EXIT=0
      echo "[$(date -u +%FT%TZ)] templated materialization OK project=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-success --stage "directors" --project-id "$PROJECT_ID" \
        --message "Templated compositions materialized deterministically" || true
    else
      MAT_EXIT=$?
      echo "[$(date -u +%FT%TZ)] FATAL type=templated_materialize_failed project=$PROJECT_ID exit=$MAT_EXIT" >&2
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
        --error-type "TEMPLATE_MATERIALIZATION_FAILED" --message "Materializer exited $MAT_EXIT" || true
      MATERIALIZE_EXIT=6
      DIRECTOR_EXIT=6
    fi
  else
    echo "[$(date -u +%FT%TZ)] FATAL type=templated_content_missing project=$PROJECT_ID" >&2
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
      --error-type "TEMPLATED_CONTENT_MISSING" --message "template_selection.json or template_content.json missing in templated mode" || true
    continue
  fi
fi

# set -e moved down to protect retry loop

if [ "$DIRECTOR_ARTIFACT_FALLBACK" -eq 1 ]; then
  :
elif [ "$TEMPLATE_MODE" -eq 1 ]; then
  :
elif jq empty "$DIRECTORS_JSON" 2>/dev/null; then
  jq -r '"session_id=\(.session_id // "?") is_error=\(.is_error // "?") turns=\(.num_turns // "?") cost_usd=\(.total_cost_usd // "?")"' \
    "$DIRECTORS_JSON" >> "$DIRECTORS_LOG"
  jq -r '.result // ""' "$DIRECTORS_JSON" >> "$DIRECTORS_LOG"
  if [ "$(jq -r '.is_error // false' "$DIRECTORS_JSON")" = "true" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: codex director reported execution error in output JSON" >> "$DIRECTORS_LOG"
    DIRECTOR_EXIT=3
  fi
else
  echo "[$(date -u +%FT%TZ)] WARN: codex produced no valid JSON result" >> "$DIRECTORS_LOG"
  [ $DIRECTOR_EXIT -eq 0 ] && DIRECTOR_EXIT=4
fi

END_TS=$(date -u +%s)
ELAPSED=$((END_TS - START_TS))

MAX_DIRECTOR_RETRIES="${MAX_DIRECTOR_RETRIES:-3}"
DIRECTOR_ATTEMPT=1

# Templated mode materializes in the block above; no generative retry loop.
validate_current_director_artifacts() {
  local output status
  output=$("$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" \
    --min-mtime-ns "$DIRECTOR_ATTEMPT_START_NS" --require-compositions 2>&1)
  status=$?
  if [ "$status" -eq 0 ]; then
    if ! "$PY" -c 'import pathlib,sys
root = pathlib.Path(sys.argv[1]); cutoff = int(sys.argv[2])
paths = [root / name / "index.html" for name in ("hyperframes", "hyperframes_reels")]
raise SystemExit(0 if all(p.is_file() and p.stat().st_mtime_ns >= cutoff for p in paths) else 1)' \
        "$PROJECT_DIR" "$DIRECTOR_ATTEMPT_START_NS"; then
      DIRECTOR_VALIDATION_ERRORS="Both compositions must be written by the current director attempt"
      printf '%s\n' "$DIRECTOR_VALIDATION_ERRORS" >> "$DIRECTORS_LOG"
      return 1
    fi
    DIRECTOR_VALIDATION_ERRORS=""
  else
    DIRECTOR_VALIDATION_ERRORS="$output"
  fi
  if [ -n "$output" ]; then
    printf '%s\n' "$output" >> "$DIRECTORS_LOG"
  fi
  return "$status"
}

if [ -n "$REHEARSAL_MANIFEST" ]; then
  if "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --require-compositions; then
    DIRECTOR_EXIT=0
  else
    DIRECTOR_EXIT=6
  fi
elif [ "$TEMPLATE_MODE" -eq 1 ]; then
  if [ "$DIRECTOR_EXIT" -eq 0 ] && [ "${MATERIALIZE_EXIT:-0}" -eq 0 ] && validate_current_director_artifacts; then
    DIRECTOR_EXIT=0
  else
    DIRECTOR_EXIT=6
  fi
else
while true; do
  if [ "$DIRECTOR_EXIT" -eq 0 ] && validate_current_director_artifacts; then
    break
  fi
  if [ "$DIRECTOR_ATTEMPT" -ge "$MAX_DIRECTOR_RETRIES" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: director artifacts incomplete or failed after $MAX_DIRECTOR_RETRIES attempts" >> "$DIRECTORS_LOG"
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
      --error-type "DIRECTOR_INCOMPLETE" --message "Director artifacts incomplete after $MAX_DIRECTOR_RETRIES attempts" \
      --attempt "$DIRECTOR_ATTEMPT" --max-attempts "$MAX_DIRECTOR_RETRIES" || true
    DIRECTOR_EXIT=6
    break
  fi
  DIRECTOR_ATTEMPT=$((DIRECTOR_ATTEMPT + 1))
  echo "[$(date -u +%FT%TZ)] WARN: director artifacts incomplete/error (attempt $DIRECTOR_ATTEMPT/$MAX_DIRECTOR_RETRIES); retrying" >> "$DIRECTORS_LOG"
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-retry --stage "directors" --project-id "$PROJECT_ID" \
    --reason "Director incomplete/failed, retrying foreground turn" --attempt "$DIRECTOR_ATTEMPT" --max-attempts "$MAX_DIRECTOR_RETRIES" || true
  # Capture diagnostics even when the director process itself failed, then
  # pass actionable seek-safety errors into the existing bounded repair turn.
  validate_current_director_artifacts || true
  RETRY_PROMPT="$(render_director_prompt "$PROMPT_DIR/director_retry.prompt.md")" || {
    echo "[$(date -u +%FT%TZ)] ERROR: missing director retry prompt" >> "$DIRECTORS_LOG"
    DIRECTOR_EXIT=6
    break
  }
  if [ -n "$DIRECTOR_VALIDATION_ERRORS" ]; then
    RETRY_PROMPT="$(printf '%s\n\nValidation errors to fix in the composition HTML:\n%s' "$RETRY_PROMPT" "$DIRECTOR_VALIDATION_ERRORS")"
  fi
  DIRECTOR_ATTEMPT_START_NS="$("$PY" -c 'import time; print(time.time_ns())')" || exit 1
  RETRY_EXIT=0
  run_directors "$RETRY_PROMPT" > "$DIRECTORS_JSON.retry" 2>> "$DIRECTORS_LOG" || RETRY_EXIT=$?
  if [ -s "$PROJECT_DIR/hyperframes/index.html" ] && [ ! -s "$PROJECT_DIR/hyperframes_reels/index.html" ]; then
      mkdir -p "$PROJECT_DIR/hyperframes_reels"
      cp "$PROJECT_DIR/hyperframes/index.html" "$PROJECT_DIR/hyperframes_reels/index.html" || true
  fi
  if [ -s "$PROJECT_DIR/hyperframes_reels/index.html" ] && [ ! -s "$PROJECT_DIR/hyperframes/index.html" ]; then
      mkdir -p "$PROJECT_DIR/hyperframes"
      cp "$PROJECT_DIR/hyperframes_reels/index.html" "$PROJECT_DIR/hyperframes/index.html" || true
  fi
  if [ "$RETRY_EXIT" -eq 0 ] && jq empty "$DIRECTORS_JSON.retry" 2>/dev/null && [ "$(jq -r '.is_error // false' "$DIRECTORS_JSON.retry")" != "true" ] && validate_current_director_artifacts; then
    mv "$DIRECTORS_JSON.retry" "$DIRECTORS_JSON"
    DIRECTOR_EXIT=0
  else
    DIRECTOR_EXIT=6
  fi
done
fi

set -e
# A failed process/result remains failed even if old artifacts validate.
# Recovery must pass the current-attempt gates in the bounded retry loop.

if [ "$DIRECTOR_EXIT" -eq 0 ]; then
  if [ ! -s "$PROJECT_DIR/artifacts/news_evidence.json" ]; then
    "$PY" "$ROOT/scripts/bind_news_evidence.py" "$PROJECT_DIR" || true
  fi
  NEWS_EVIDENCE_LOG="$(mktemp "$ROOT/logs/news_evidence_${PROJECT_ID}_XXXXXX.json")"
  if ! validate_project_news_evidence "$PROJECT_DIR" "$NEWS_EVIDENCE_LOG"; then
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "news_evidence" --project-id "$PROJECT_ID" \
      --error-type "NEWS_EVIDENCE_INVALID" --message "Frozen source evidence failed validation" || true
    "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
      "news evidence missing or invalid; see $NEWS_EVIDENCE_LOG" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
    continue
  fi
  echo "[$(date -u +%FT%TZ)] directors OK project=$PROJECT_ID exit=0 elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-success --stage "directors" --project-id "$PROJECT_ID" \
    --message "Director artifacts generated and validated" || true
  # Hard gate: both compositions must exist at canonical paths before render.
  HYPER_FULL="$PROJECT_DIR/hyperframes/index.html"
  HYPER_REELS="$PROJECT_DIR/hyperframes_reels/index.html"
  if [ -s "$HYPER_FULL" ] && [ -s "$HYPER_REELS" ]; then
    echo "[$(date -u +%FT%TZ)] artifacts OK" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  else
    if [ ! -s "$HYPER_FULL" ]; then
      echo "[$(date -u +%FT%TZ)] FATAL type=no_full_composition PROJECT_ID=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      echo "[$(date -u +%FT%TZ)] FATAL type=no_full_composition PROJECT_ID=$PROJECT_ID" >&2
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
        --error-type "MISSING_FULL_COMPOSITION" --message "Full composition index.html missing or empty" || true
    fi
    if [ ! -s "$HYPER_REELS" ]; then
      echo "[$(date -u +%FT%TZ)] FATAL type=no_reels_composition PROJECT_ID=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      echo "[$(date -u +%FT%TZ)] FATAL type=no_reels_composition PROJECT_ID=$PROJECT_ID" >&2
      "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
        --error-type "MISSING_REELS_COMPOSITION" --message "Reels composition index.html missing or empty" || true
    fi
    COMPOSITION_FAILURE_REASON="missing required HyperFrames composition:"
    [ -s "$HYPER_FULL" ] || COMPOSITION_FAILURE_REASON="$COMPOSITION_FAILURE_REASON full"
    [ -s "$HYPER_REELS" ] || COMPOSITION_FAILURE_REASON="$COMPOSITION_FAILURE_REASON reels"
    COMPOSITION_FAILURE_REASON="$COMPOSITION_FAILURE_REASON; see $ROOT/logs/directors_${PROJECT_ID}.log"
    "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
      "$COMPOSITION_FAILURE_REASON" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
    continue
  fi
else
  echo "[$(date -u +%FT%TZ)] directors FAIL project=$PROJECT_ID exit=$DIRECTOR_EXIT elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  echo "  see full transcript: $DIRECTORS_LOG" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
    --error-type "DIRECTOR_FAILURE" --message "Director run failed with exit code $DIRECTOR_EXIT" || true
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "Director run failed with exit code $DIRECTOR_EXIT after $DIRECTOR_ATTEMPT attempt(s); see $DIRECTORS_LOG" \
    || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# Step 3: Render video (120s + 60s Reels) + sanity check (P4)
REHEARSAL_TERMINAL_STAGE="project:${PROJECT_ID}:render_and_quality"
cd "$ROOT/projects/$PROJECT_ID"
chmod -R 777 "$PROJECT_DIR" 2>/dev/null || true
mkdir -p renders

# Autonomous directors may record generated assets in the manifest without materializing files.
validate_project_background_music() {
  local project_root="$1"
  local project_id="$2"
  local music="$project_root/assets/music-bg.mp3"
  local narration="$project_root/assets/narration.mp3"
  local probe_output
  if [ ! -s "$music" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: background music asset missing for $project_id" >&2
    return 1
  fi
  if ! probe_output=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$music" 2>/dev/null; probe_status=$?; printf '\034'; exit "$probe_status"); then
    echo "[$(date -u +%FT%TZ)] ERROR: could not probe background music duration for $project_id" >&2
    return 1
  fi
  probe_output=${probe_output%$'\034'}
  if [[ "$probe_output" == *$'\n' ]]; then probe_output=${probe_output%$'\n'}; fi
  if [[ "$probe_output" == *$'\r' ]]; then probe_output=${probe_output%$'\r'}; fi
  if [[ "$probe_output" == *$'\n'* || "$probe_output" == *$'\r'* ]] || ! python3 -c 'import math, re, sys
value = sys.argv[1]
if not re.fullmatch(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
    raise SystemExit(1)
try:
    duration = float(value)
except (OverflowError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if math.isfinite(duration) and duration > 5 else 1)' "$probe_output"; then
    echo "[$(date -u +%FT%TZ)] ERROR: background music duration must be a single finite numeric value greater than 5s (got ${probe_output:-empty}) for $project_id" >&2
    return 1
  fi

  if cmp -s "$narration" "$music"; then
    echo "[$(date -u +%FT%TZ)] ERROR: background music is byte-identical to narration for $project_id" >&2
    return 1
  fi
}

materialize_hyperframes_assets() {
  local project_root="$1"
  local narration="$project_root/assets/narration.mp3"
  local reels_narration="$project_root/assets/narration_reels.mp3"
  local narration_text="$project_root/artifacts/narration_vi_text.txt"
  local script_json="$project_root/artifacts/script_vi.json"
  if [ ! -s "$script_json" ] && [ -s "$project_root/artifacts/script.json" ]; then script_json="$project_root/artifacts/script.json"; fi
  local script_spoken="$project_root/04_audio/script_spoken.md"
  local source_fonts="$ROOT/.agents/skills/hyperframes-media/assets/fonts"
  local fallback_regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
  [ -s "$fallback_regular" ] || fallback_regular="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
  local fallback_bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
  [ -s "$fallback_bold" ] || fallback_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
  find_vietnamese_font() {
    local file="$1"
    local candidate
    for candidate in \
      "$source_fonts/$file" \
      "$ROOT"/projects/*/hyperframes/assets/"$file" \
      "$ROOT"/projects/*/hyperframes_reels/assets/"$file"; do
      [ -s "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
    done
    return 1
  }

  mkdir -p "$project_root/artifacts" "$project_root/assets" "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
  : > "$narration_text"
  if [ ! -s "$narration" ] && [ -s "$project_root/assets/voice/narration.mp3" ]; then
    cp "$project_root/assets/voice/narration.mp3" "$narration"
  fi
  if [ "$(wc -c < "$narration_text" 2>/dev/null || echo 0)" -le 1 ] && [ -s "$script_json" ]; then
    jq -r 'if (.sections // null) then [.sections[]? | .text_vi // .narration_vi // .text // .narration // empty] | join(" ") else (.text_vi // .narration_vi // .text // .narration // .script // empty) end' "$script_json" > "$narration_text"
  fi
  if [ ! -s "$narration_text" ] && [ -s "$script_spoken" ]; then
    tr '\n' ' ' < "$script_spoken" | sed -E 's/^[[:space:]]*#+[[:space:]]*//; s/[*_`]//g' > "$narration_text"
  fi
  local narration_duration=0
  if [ -s "$narration" ]; then
    narration_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  fi
  local narration_stale=0
  if [ ! -s "$narration" ] || { [ -s "$narration_text" ] && [ "$narration_text" -nt "$narration" ]; }; then
    narration_stale=1
  fi
  if [ -z "$REHEARSAL_MANIFEST" ] && [ -s "$narration_text" ] && command -v edge-tts >/dev/null 2>&1 && { awk -v d="$narration_duration" 'BEGIN{exit !(d <= 5)}' || [ "$narration_stale" = 1 ]; }; then
    "$PY" "$ROOT/tools/narration_text.py" --in-file "$narration_text" --out-file "$narration_text.prepared"
    edge-tts --voice vi-VN-HoaiMyNeural --text "$(cat "$narration_text.prepared")" --write-media "$narration"
    rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
  fi

  # Captions are generated after the Reels narration has its final audio bytes,
  # and each rendition is transcribed independently in strict cached-only mode.
  if [ ! -s "$narration" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration asset missing for $PROJECT_ID"
    return 1
  fi
  narration_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  if ! awk -v d="$narration_duration" 'BEGIN{exit !(d > 5)}'; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration duration ${narration_duration}s <=5s for $PROJECT_ID"
    return 1
  fi
  validate_project_background_music "$project_root" "$PROJECT_ID" || return 1
  # Reels/Shorts must stay under the 60s platform limit. Derive a capped
  # narration for the reels composition so its aligned timeline is <=60s.
  local reels_cap=58
  if awk -v d="$narration_duration" -v c="$reels_cap" 'BEGIN{exit !(d > c)}'; then
    "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" -c copy "$reels_narration" 2>/dev/null \
      || "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" "$reels_narration"
  else
    cp "$narration" "$reels_narration"
  fi
  "$PY" "$ROOT/scripts/generate_news_captions.py" "$narration" "$project_root/hyperframes/assets" || return 1
  "$PY" "$ROOT/scripts/generate_news_captions.py" "$reels_narration" "$project_root/hyperframes_reels/assets" || return 1
  for composition in hyperframes hyperframes_reels; do
    local target="$project_root/$composition/assets"
    if [ "$composition" = "hyperframes_reels" ]; then
      cp "$reels_narration" "$target/narration_reels.mp3"
      cp "$reels_narration" "$target/narration.mp3"
    else
      cp "$narration" "$target/narration.mp3"
    fi
    cp "$project_root/assets/music-bg.mp3" "$target/music-bg.mp3"
    if [ -s "$source_fonts/BeVietnamPro-Regular.ttf" ]; then cp "$source_fonts/BeVietnamPro-Regular.ttf" "$target/BeVietnamPro-Regular.ttf"; else cp "$fallback_regular" "$target/BeVietnamPro-Regular.ttf"; fi
    if [ -s "$source_fonts/BeVietnamPro-Bold.ttf" ]; then cp "$source_fonts/BeVietnamPro-Bold.ttf" "$target/BeVietnamPro-Bold.ttf"; else cp "$fallback_bold" "$target/BeVietnamPro-Bold.ttf"; fi
    if [ -s "$source_fonts/BeVietnamPro-ExtraBold.ttf" ]; then cp "$source_fonts/BeVietnamPro-ExtraBold.ttf" "$target/BeVietnamPro-ExtraBold.ttf"; else cp "$fallback_bold" "$target/BeVietnamPro-ExtraBold.ttf"; fi
  done
  # Repair is a generic mutation path; skip it on templated compositions so
  # provenance hashes recorded by the materializer stay valid.
  if [ "${TEMPLATE_MODE:-0}" -eq 1 ]; then
    echo "skip repair_hyperframes_quality (templated compositions are deterministic)"
  else
    "$PY" "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root" --strict || return 1
  fi
  for composition in hyperframes hyperframes_reels; do
    local target="$project_root/$composition/assets"
    "$PY" "$ROOT/scripts/install_news_captions.py" \
      "$project_root/$composition/index.html" \
      "$target/narration.mp3" \
      "$target/word_timestamps.json" || return 1
  done
}
if ! materialize_hyperframes_assets "$ROOT/projects/$PROJECT_ID"; then
  echo "[$(date -u +%FT%TZ)] ERROR: HyperFrames asset materialization/repair failed for $PROJECT_ID" >&2
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "asset_materialization" --project-id "$PROJECT_ID" \
    --error-type "HYPERFRAMES_ASSET_REPAIR_FAILED" --message "HyperFrames asset materialization or repair failed" || true
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "HyperFrames asset materialization or repair failed" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

FULL_COMP=""
if [ -d "hyperframes" ]; then
  FULL_COMP="hyperframes"
elif [ -d "Hyperframes" ]; then
  FULL_COMP="Hyperframes"
fi

REELS_COMP=""
if [ -d "hyperframes_reels" ]; then
  REELS_COMP="hyperframes_reels"
elif [ -d "Hyperframes_reels" ]; then
  REELS_COMP="Hyperframes_reels"
fi

if [ -z "$FULL_COMP" ] || [ -z "$REELS_COMP" ] || [ ! -f "$FULL_COMP/index.html" ] || [ ! -f "$REELS_COMP/index.html" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: both HyperFrames composition index files are required for $PROJECT_ID; skipping candidate" >&2
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "missing full/reels HyperFrames composition index" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# Fix composition asset references (incorrect relative paths)
# Skip on templated compositions to preserve byte-stable materializer output.
if [ "${TEMPLATE_MODE:-0}" -eq 1 ]; then
  echo "skip sed asset rewrite (templated compositions)"
else
  sed -i 's|\.\./assets/|assets/|g' "$FULL_COMP/index.html" "$REELS_COMP/index.html"
fi

rm -f renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4
set +e
"$HYPERFRAMES_BIN" render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
RENDER_FULL_EXIT=$?
"$HYPERFRAMES_BIN" render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
RENDER_REELS_EXIT=$?
set -e
if [ "$RENDER_FULL_EXIT" -ne 0 ] || [ "$RENDER_REELS_EXIT" -ne 0 ]; then
  RENDER_FAILURE_REASON="HyperFrames render command failed: full_exit=$RENDER_FULL_EXIT reels_exit=$RENDER_REELS_EXIT"
  echo "[$(date -u +%FT%TZ)] ERROR: $RENDER_FAILURE_REASON for $PROJECT_ID" >&2
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "render" --project-id "$PROJECT_ID" \
    --error-type "RENDER_COMMAND_FAILED" --message "$RENDER_FAILURE_REASON" || true
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "$RENDER_FAILURE_REASON" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# ===== CODEX AGENT STRICT QUALITY VALIDATION =====
echo "[$(date -u +%FT%TZ)] Codex Agent Strict Quality Validation Started"

# Step 1: Base render quality validation (existing)
if "$PY" "$ROOT/scripts/validate_render_quality.py" "$ROOT/projects/$PROJECT_ID" --ffprobe "$FFPROBE_BIN" --ffmpeg "$FFMPEG_BIN" --reels-max-duration 60 --strict; then
  VALIDATE_RENDER_EXIT=0
else
  VALIDATE_RENDER_EXIT=$?
fi

if [ $VALIDATE_RENDER_EXIT -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: Base render validation failed for $PROJECT_ID" >&2
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "render_validation" --project-id "$PROJECT_ID" \
    --error-type "RENDER_VALIDATION_FAILED" --message "Base render validation failed" || true
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "Base render quality validation failed" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# Check if videos exist
RENDER_MISSING=0
for render in renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4; do
  if [ ! -s "$render" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: render missing or empty: $render for $PROJECT_ID" >&2
    RENDER_MISSING=1
  fi
done
if [ $RENDER_MISSING -ne 0 ]; then
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "one or more expected renders are missing or empty" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# Step 2: Create publish_metadata.json first (needed for Codex validation)
TITLE=$(jq -r '.title // empty' artifacts/script_vi.json 2>/dev/null || echo "")
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.concept_options[0].title // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
fi
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.topic // .title // "News Video"' artifacts/research_brief.json 2>/dev/null || echo "News Video")
fi

# Ensure title contains required hashtags
if [[ "$TITLE" != *"#tintuc"* || "$TITLE" != *"#congnghe"* || "$TITLE" != *"#ai"* ]]; then
  BASE_TITLE=$(echo "$TITLE" | sed 's/ #tintuc.*//' | sed 's/ #congnghe.*//' | sed 's/ #ai.*//')
  TITLE="${BASE_TITLE:0:80} #tintuc #congnghe #ai"
fi

# Create publish_metadata.json for validation
if [ -s "$PROJECT_DIR/renders/final_reels_vi_9x16.mp4" ] && [ -s "$PROJECT_DIR/renders/final_full_vi_9x16.mp4" ]; then
  jq -n \
  --arg id "$PROJECT_ID" \
  --arg title "$TITLE" \
  --arg desc "$(jq -r '.description // ""' artifacts/script_vi.json 2>/dev/null || echo "")" \
  --arg yt_shorts "renders/final_reels_vi_9x16.mp4" \
  --arg tiktok "renders/final_full_vi_9x16.mp4" \
  --arg fb_video "renders/final_full_vi_9x16.mp4" \
  --arg ig_reels "renders/final_reels_vi_9x16.mp4" \
  --argjson feed_stale "$FEED_STALE" \
  '{
    id: $id,
    topic: $title,
    title: $title,
    description: $desc,
    yt_shorts: $yt_shorts,
    tiktok: $tiktok,
    fb_video: $fb_video,
    ig_reels: $ig_reels,
    feed_stale: $feed_stale
  }' > "$PROJECT_DIR/publish_metadata.json"
else
  echo "[$(date -u +%FT%TZ)] ERROR: Missing video files for $PROJECT_ID" >&2
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "publish metadata not created because one or more video files are missing" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

# Step 3: Codex Agent Strict Quality Validation
echo "[$(date -u +%FT%TZ)] Running Codex Agent validation..."

# Set max retry attempts
MAX_RETRIES="${CODEX_VALIDATION_RETRIES:-3}"
VALIDATION_PASSED=0
VAL_SCRIPT="$ROOT/scripts/codex_agent_validation.py"
[ -f "$VAL_SCRIPT" ] || { echo "ERROR: codex_agent_validation.py not found"; exit 1; }

for ((retry=1; retry<=$MAX_RETRIES; retry++)); do
  echo "[$(date -u +%FT%TZ)] Codex Validation Attempt $retry/$MAX_RETRIES"

  REVIEW_ARGS=()
  if [ -n "$REHEARSAL_MANIFEST" ]; then
    REVIEW_ARGS=(--test-review-reply "$PROJECT_DIR/artifacts/reviewer_reply.json")
  fi
  if "$PY" "$ROOT/scripts/codex_agent_validation.py" "$ROOT/projects/$PROJECT_ID" \
      --strict \
      --retry "$MAX_RETRIES" \
      --ffprobe "$FFPROBE_BIN" \
      --ffmpeg "$FFMPEG_BIN" \
      "${REVIEW_ARGS[@]}"; then
    VALIDATION_EXIT=0
  else
    VALIDATION_EXIT=$?
  fi

  if [ $VALIDATION_EXIT -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] 🟢 Codex Agent Strict Quality Validation PASSED"
    VALIDATION_PASSED=1
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-success --stage "codex_validation" --project-id "$PROJECT_ID" \
      --message "Codex agent validation passed on attempt $retry/$MAX_RETRIES" || true
    break
  else
    echo "[$(date -u +%FT%TZ)] ❌ Codex Agent validation failed (attempt $retry/$MAX_RETRIES)"
    "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-retry --stage "codex_validation" --project-id "$PROJECT_ID" \
      --reason "Codex agent validation failed, retrying" --attempt "$retry" --max-attempts "$MAX_RETRIES" || true

    # Only retry if we haven't exhausted attempts
    if [ $retry -lt $MAX_RETRIES ]; then
      echo "[$(date -u +%FT%TZ)] Retrying validation..."
      sleep 5  # Brief pause before retry
    fi
  fi
done

if [ $VALIDATION_PASSED -eq 0 ]; then
  echo "[$(date -u +%FT%TZ)] 🔴 FINAL: Codex Agent Strict Quality Validation FAILED after $MAX_RETRIES attempts" >&2
  echo "[$(date -u +%FT%TZ)] Project: $PROJECT_ID" >&2
  echo "[$(date -u +%FT%TZ)] Check validation reports in project directory" >&2
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "codex_validation" --project-id "$PROJECT_ID" \
    --error-type "VALIDATION_FAILED" --message "Codex agent validation failed after $MAX_RETRIES attempts" \
    --attempt "$MAX_RETRIES" --max-attempts "$MAX_RETRIES" || true

  echo "[$(date -u +%FT%TZ)] Preserving failed project in quarantine and continuing to next candidate." >&2
  "$PY" "$ROOT/lib/news_failure_quarantine.py" "$ROOT/projects" "$PROJECT_ID" \
    "Codex validation failed after $MAX_RETRIES attempts" || echo "[$(date -u +%FT%TZ)] ERROR: failed to quarantine project $PROJECT_ID; source remains in place" >&2
  continue
fi

if [ "$FEED_STALE" -eq 1 ]; then
  echo "[$(date -u +%FT%TZ)] NOTICE: Render completed using STALE feed data."
fi

# Step 4: Create publish_metadata.json
TITLE=$(jq -r '.title // empty' artifacts/script_vi.json 2>/dev/null || echo "")
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.concept_options[0].title // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
fi
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.topic // .title // "News Video"' artifacts/research_brief.json 2>/dev/null || echo "News Video")
fi

# Ensure title contains required hashtags (#tintuc #congnghe #ai)
if [[ "$TITLE" != *"#tintuc"* || "$TITLE" != *"#congnghe"* || "$TITLE" != *"#ai"* ]]; then
  BASE_TITLE=$(echo "$TITLE" | sed 's/ #tintuc.*//' | sed 's/ #congnghe.*//' | sed 's/ #ai.*//')
  TITLE="${BASE_TITLE:0:80} #tintuc #congnghe #ai"
fi
# Safeguard: ensure it fits within 100 chars for YT Shorts
if [ ${#TITLE} -gt 100 ]; then
  # Strip any existing suffix and truncate base title to 80 chars, then append required hashtags
  BASE_TITLE=$(echo "$TITLE" | sed 's/ #tintuc.*//' | sed 's/ #congnghe.*//' | sed 's/ #ai.*//')
  TITLE="${BASE_TITLE:0:80} #tintuc #congnghe #ai"
fi

CONCEPT_HOOK=$(jq -r '.concept_options[0].hook // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
CONCEPT_MSG=$(jq -r '.concept_options[0].core_message // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
CONCEPT_CTA=$(jq -r '.concept_options[0].cta // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")

DESCRIPTION=""
if [ -n "$CONCEPT_HOOK" ]; then DESCRIPTION="$CONCEPT_HOOK"; fi
if [ -n "$CONCEPT_MSG" ]; then
  if [ -n "$DESCRIPTION" ]; then DESCRIPTION="$DESCRIPTION. $CONCEPT_MSG"; else DESCRIPTION="$CONCEPT_MSG"; fi
fi
if [ -n "$CONCEPT_CTA" ]; then
  if [ -n "$DESCRIPTION" ]; then DESCRIPTION="$DESCRIPTION. $CONCEPT_CTA"; else DESCRIPTION="$CONCEPT_CTA"; fi
fi
if [ -z "$DESCRIPTION" ]; then
  DESCRIPTION="Điểm tin công nghệ AI mới nhất."
fi
DESCRIPTION="$DESCRIPTION"$'\n\n'"#tintuc #congnghe #giaoduc #hoctap #ai #vietnam"

# On the templated path, bind template provenance into the publish metadata so
# downstream tooling can carry the deterministic composition + content hashes.
TEMPLATE_PROV_JSON="{}"
if [ "${TEMPLATE_MODE:-0}" -eq 1 ] && [ -s template_provenance.json ]; then
  TEMPLATE_PROV_JSON=$(jq -c '{
    template_id: .template_id,
    template_version: .template_version,
    composition_source_sha256: .composition_source_sha256,
    content_instance_sha256: .content_instance_sha256,
    caption_display_verified: .caption_display_verified
  }' template_provenance.json) || TEMPLATE_PROV_JSON="{}"
fi

jq -n \
  --arg id "$PROJECT_ID" \
  --arg title "$TITLE" \
  --arg description "$DESCRIPTION" \
  --argjson feed_stale "$FEED_STALE" \
  --argjson template_prov "$TEMPLATE_PROV_JSON" \
  '{
    id: $id,
    topic: $title,
    title: $title,
    description: $description,
    yt_shorts: "renders/final_reels_vi_9x16.mp4",
    tiktok: "renders/final_full_vi_9x16.mp4",
    fb_video: "renders/final_full_vi_9x16.mp4",
    ig_reels: "renders/final_reels_vi_9x16.mp4",
    feed_stale: $feed_stale
  } + (if ($template_prov|length) > 0 then $template_prov else {} end)' > publish_metadata.json

# Step 4.5: Run copyright preflight (if files exist)
if [ -f "renders/final_full_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_full_vi_9x16.mp4"
fi
if [ -f "renders/final_reels_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_reels_vi_9x16.mp4"
fi

SUCCESSFUL_COUNT=$((SUCCESSFUL_COUNT + 1))
if [ -n "$REHEARSAL_MANIFEST" ]; then
  REHEARSAL_SUCCESSFUL_IDS+=("$PROJECT_ID")
fi
REHEARSAL_TERMINAL_STAGE="project:${PROJECT_ID}:completed"
if [ "$SUCCESSFUL_COUNT" -ge "$EXPECTED_SUCCESS_COUNT" ]; then
  echo "[$(date -u +%FT%TZ)] Successfully generated and validated $EXPECTED_SUCCESS_COUNT projects. Breaking loop early."
  break
fi

done

# Step 5: (Removed atomic activation; now handled strictly by run_strict_docker_publish.sh's queue-next-day stage)
cd "$ROOT"

if [ -n "$REHEARSAL_MANIFEST" ] && [ "$SUCCESSFUL_COUNT" -ne "$EXPECTED_SUCCESS_COUNT" ]; then
  REHEARSAL_TERMINAL_STAGE="incomplete_rehearsal"
  echo "[$(date -u +%FT%TZ)] ERROR: rehearsal requires all $EXPECTED_SUCCESS_COUNT requested projects to pass; got $SUCCESSFUL_COUNT" >&2
  exit 1
fi
if [ "$SUCCESSFUL_COUNT" -eq "$EXPECTED_SUCCESS_COUNT" ]; then
  REHEARSAL_TERMINAL_STAGE="completed"
  echo "Daily pipeline completed: ${PROJECT_IDS[*]} (Feed stale: $FEED_STALE, Successful: $SUCCESSFUL_COUNT)"
  exit 0
elif [ "$SUCCESSFUL_COUNT" -gt 0 ]; then
  REHEARSAL_TERMINAL_STAGE="partial_completion"
  echo "[$(date -u +%FT%TZ)] PARTIAL: Daily pipeline achieved $SUCCESSFUL_COUNT/$EXPECTED_SUCCESS_COUNT successful validated projects." >&2
  exit 2
else
  REHEARSAL_TERMINAL_STAGE="failed"
  echo "[$(date -u +%FT%TZ)] ERROR: no candidate passed strict generation and validation" >&2
  exit 1
fi
# Next-day scheduling and publishing is now fully managed by the strict orchestrator.
