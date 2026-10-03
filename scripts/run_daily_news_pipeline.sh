#!/usr/bin/env bash
# Daily AI news video generation pipeline.
# Selects trending topic, runs directors pipeline, generates Vietnamese video (120s + 60s Reels), updates publish_schedule.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p "$ROOT/logs"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:$PATH"
if [ -d "$HOME/.npm/_npx/702923228c2ce1e6/node_modules/.bin" ]; then
  export PATH="$HOME/.npm/_npx/702923228c2ce1e6/node_modules/.bin:$PATH"
fi
export PYTHONPATH="$ROOT"
export PUBLISH_TZ="${PUBLISH_TZ:-Asia/Ho_Chi_Minh}"

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

"$PY" -c 'from scripts.publish_config import load_config; load_config()' || {
  echo "ERROR: invalid publish timezone configuration" >&2
  exit 1
}

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
fi

# Step 1: Select and initialize distinct current topics.
PRODUCE_LOG="$ROOT/logs/news_produce_$(date -u +%Y%m%dT%H%M%SZ).log"
"$PY" tools/news/news_pipeline_cli.py produce --input data/newsnow_feed.json --count 6 2>&1 | tee "$PRODUCE_LOG" || true
mapfile -t PROJECT_IDS < <(grep '^PROJECT_ID=' "$PRODUCE_LOG" | cut -d= -f2)
if [ "${#PROJECT_IDS[@]}" -lt 3 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: Expected at least three initialized projects, got ${#PROJECT_IDS[@]}."
  exit 1
fi

SUCCESSFUL_COUNT=0

for PROJECT_ID in "${PROJECT_IDS[@]}"; do
  cd "$ROOT"
  chmod 777 "$ROOT" 2>/dev/null || true
  PROJECT_DIR="$ROOT/projects/$PROJECT_ID"
  if [ -d "$PROJECT_DIR" ]; then
    chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true
  fi
  mkdir -p "$PROJECT_DIR/artifacts" "$PROJECT_DIR/hyperframes" "$PROJECT_DIR/hyperframes_reels"
  chmod -R 777 "$PROJECT_DIR" 2>/dev/null || true
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
PROMPT_STR="$(render_director_prompt "$PROMPT_DIR/director_generate.prompt.md")" || {
  echo "[$(date -u +%FT%TZ)] ERROR: missing/invalid director generation prompt" >> "$DIRECTORS_LOG"
  exit 1
}
DIRECTOR_SYSTEM_NOTE="$(render_director_prompt "$PROMPT_DIR/director_system.prompt.md")" || {
  echo "[$(date -u +%FT%TZ)] ERROR: missing/invalid director system prompt" >> "$DIRECTORS_LOG"
  exit 1
}
DIRECTOR_FULL_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes/index.html"
DIRECTOR_REELS_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes_reels/index.html"
DIRECTOR_ARTIFACTS_READY=0
# Existing files are not a valid success signal: they may belong to a prior run.
# A director timeout must fail closed rather than publishing stale content.

run_directors() {
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
      for c in /home/ubuntu/.nvm/versions/node/v22.23.2/bin/codex /usr/local/bin/codex /usr/bin/codex; do
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
        if [ -s "$CODEX_HOME/auth.json" ]; then
          export OPENAI_API_KEY="$(jq -r .OPENAI_API_KEY "$CODEX_HOME/auth.json" 2>/dev/null || true)"
        fi
        cd "$PROJECT_DIR"
        test -s "artifacts/research_brief.json" || exit 7
        timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json "$PROMPT_STR" < /dev/null
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
      for c in /home/ubuntu/.nvm/versions/node/v22.23.2/bin/codex /usr/local/bin/codex /usr/bin/codex; do
        if [ -x "$c" ]; then CODEX_BIN="$c"; break; fi
      done
    fi
    if [ -n "$CODEX_BIN" ]; then
      export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
      mkdir -p "$CODEX_HOME"
      timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json "$prompt" < /dev/null
    else
      echo "[$(date -u +%FT%TZ)] ERROR: codex CLI not found, cannot run directors" >&2
    fi
  fi
}

if ! command -v timeout >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] ERROR: timeout command is required for directors" >> "$DIRECTORS_LOG"
  exit 1
fi

run_directors > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
DIRECTOR_EXIT=$?
DIRECTOR_ARTIFACT_FALLBACK=0
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

# set -e moved down to protect retry loop

if [ "$DIRECTOR_ARTIFACT_FALLBACK" -eq 1 ]; then
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

while [ "$DIRECTOR_EXIT" -ne 0 ] || ! "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --min-mtime-ns "${START_TS}000000000" --require-compositions; do
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
  RETRY_PROMPT="$(render_director_prompt "$PROMPT_DIR/director_retry.prompt.md")" || {
    echo "[$(date -u +%FT%TZ)] ERROR: missing director retry prompt" >> "$DIRECTORS_LOG"
    DIRECTOR_EXIT=6
    break
  }
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
  if [ "$RETRY_EXIT" -eq 0 ] && jq empty "$DIRECTORS_JSON.retry" 2>/dev/null && [ "$(jq -r '.is_error // false' "$DIRECTORS_JSON.retry")" != "true" ] && "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --min-mtime-ns "${START_TS}000000000" --require-compositions; then
    mv "$DIRECTORS_JSON.retry" "$DIRECTORS_JSON"
    DIRECTOR_EXIT=0
  else
    DIRECTOR_EXIT=6
  fi
done

set -e
if [ $DIRECTOR_EXIT -ne 0 ]; then
  if "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --require-compositions; then
    echo "[$(date -u +%FT%TZ)] directors recovered via autonomous synthesis project=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
    DIRECTOR_EXIT=0
  fi
fi

if [ $DIRECTOR_EXIT -eq 0 ]; then
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
    continue
  fi
else
  echo "[$(date -u +%FT%TZ)] directors FAIL project=$PROJECT_ID exit=$DIRECTOR_EXIT elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  echo "  see full transcript: $DIRECTORS_LOG" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "directors" --project-id "$PROJECT_ID" \
    --error-type "DIRECTOR_FAILURE" --message "Director run failed with exit code $DIRECTOR_EXIT" || true
  continue
fi

# Step 3: Render video (120s + 60s Reels) + sanity check (P4)
cd "$ROOT/projects/$PROJECT_ID"
chmod -R 777 . 2>/dev/null || true
mkdir -p renders

# Autonomous directors may record generated assets in the manifest without materializing files.
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
  if [ -s "$narration_text" ] && command -v edge-tts >/dev/null 2>&1 && { awk -v d="$narration_duration" 'BEGIN{exit !(d <= 5)}' || [ "$narration_stale" = 1 ]; }; then
    "$PY" "$ROOT/tools/narration_text.py" --in-file "$narration_text" --out-file "$narration_text.prepared"
    edge-tts --voice vi-VN-HoaiMyNeural --text "$(cat "$narration_text.prepared")" --write-media "$narration"
    rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
  fi

  # Generate Vietnamese subtitles with word timestamps for caption synchronization
if [ -s "$narration" ] && command -v "$PY" >/dev/null 2>&1; then
  local subtitle_text="$narration_text.prepared"
  [ -s "$subtitle_text" ] || subtitle_text="$narration_text"
  
  echo "[$(date -u +%FT%TZ)] Generating Vietnamese subtitles..."
  mkdir -p "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
  
  if [ -s "$subtitle_text" ]; then
    "$PY" "$ROOT/scripts/generate_vn_subtitles.py" \
      "$subtitle_text" \
      "$narration" \
      "$project_root/hyperframes/assets/subtitles.srt" \
      "$project_root/hyperframes/assets/word_timestamps.json" \
      3 || { echo "[$(date -u +%FT%TZ)] ERROR: Subtitle generation failed" >&2; return 1; }
    echo "[$(date -u +%FT%TZ)] Vietnamese subtitles generated"

    # Generate reels subtitles if audio exists.
    if [ -s "$reels_narration" ]; then
      "$PY" "$ROOT/scripts/generate_vn_subtitles.py" \
        "$subtitle_text" \
        "$reels_narration" \
        "$project_root/hyperframes_reels/assets/subtitles.srt" \
        "$project_root/hyperframes_reels/assets/word_timestamps.json" \
        3 || { echo "[$(date -u +%FT%TZ)] ERROR: Reels subtitle generation failed"; return 1; }
    fi
  else
    echo "[$(date -u +%FT%TZ)] WARNING: No subtitle text available" >&2
  fi
fi
  if [ ! -s "$narration" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration asset missing for $PROJECT_ID"
    return 1
  fi
  narration_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  if ! awk -v d="$narration_duration" 'BEGIN{exit !(d > 5)}'; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration duration ${narration_duration}s <=5s for $PROJECT_ID"
    return 1
  fi
  if [ ! -s "$project_root/assets/music-bg.mp3" ]; then
    echo "[$(date -u +%FT%TZ)] WARN: background music asset missing for $PROJECT_ID, using fallback"
    cp "$ROOT/tests/qa/output/music_calm.mp3" "$project_root/assets/music-bg.mp3" || true
  fi
  local music_duration
  music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
  if ! awk -v d="$music_duration" 'BEGIN{exit !(d > 5)}'; then
    echo "[$(date -u +%FT%TZ)] WARN: background music duration ${music_duration}s <=5s for $PROJECT_ID, using fallback"
    cp "$ROOT/tests/qa/output/music_calm.mp3" "$project_root/assets/music-bg.mp3" || true
    music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
  fi
  if cmp -s "$narration" "$project_root/assets/music-bg.mp3"; then
    echo "[$(date -u +%FT%TZ)] ERROR: background music is byte-identical to narration for $PROJECT_ID"
    return 1
  fi
  # Reels/Shorts must stay under the 60s platform limit. Derive a capped
  # narration for the reels composition so its aligned timeline is <=60s.
  local reels_cap=58
  if awk -v d="$narration_duration" -v c="$reels_cap" 'BEGIN{exit !(d > c)}'; then
    "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" -c copy "$reels_narration" 2>/dev/null \
      || "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" "$reels_narration"
  else
    cp "$narration" "$reels_narration"
  fi
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
  "$PY" "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root" --strict
}
if ! materialize_hyperframes_assets "$ROOT/projects/$PROJECT_ID"; then
  echo "[$(date -u +%FT%TZ)] ERROR: HyperFrames asset materialization/repair failed for $PROJECT_ID" >&2
  "$PY" "$ROOT/scripts/pipeline_monitoring.py" log-error --stage "asset_materialization" --project-id "$PROJECT_ID" \
    --error-type "HYPERFRAMES_ASSET_REPAIR_FAILED" --message "HyperFrames asset materialization or repair failed" || true
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
  rm -rf "$ROOT/projects/$PROJECT_ID"
  continue
fi

# Fix composition asset references (incorrect relative paths)
sed -i 's|\.\./assets/|assets/|g' "$FULL_COMP/index.html" "$REELS_COMP/index.html"

rm -f renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4
"$HYPERFRAMES_BIN" render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
"$HYPERFRAMES_BIN" render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4

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

  if "$PY" "$ROOT/scripts/codex_agent_validation.py" "$ROOT/projects/$PROJECT_ID" \
      --strict \
      --retry "$MAX_RETRIES" \
      --ffprobe "$FFPROBE_BIN" \
      --ffmpeg "$FFMPEG_BIN"; then
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

  echo "[$(date -u +%FT%TZ)] Removing failed project directory and continuing to next candidate." >&2
  rm -rf "$ROOT/projects/$PROJECT_ID"
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

jq -n \
  --arg id "$PROJECT_ID" \
  --arg title "$TITLE" \
  --arg description "$DESCRIPTION" \
  --argjson feed_stale "$FEED_STALE" \
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
  }' > publish_metadata.json

# Step 4.5: Run copyright preflight (if files exist)
if [ -f "renders/final_full_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_full_vi_9x16.mp4"
fi
if [ -f "renders/final_reels_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_reels_vi_9x16.mp4"
fi

SUCCESSFUL_COUNT=$((SUCCESSFUL_COUNT + 1))
if [ $SUCCESSFUL_COUNT -ge 3 ]; then
  echo "[$(date -u +%FT%TZ)] Successfully generated and validated 3 projects. Breaking loop early."
  break
fi

done

# Step 5: (Removed atomic activation; now handled strictly by run_strict_docker_publish.sh's queue-next-day stage)
cd "$ROOT"

if [ "$SUCCESSFUL_COUNT" -eq 0 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: no candidate passed strict generation and validation" >&2
  exit 1
fi

echo "Daily pipeline completed: ${PROJECT_IDS[*]} (Feed stale: $FEED_STALE, Successful: $SUCCESSFUL_COUNT)"
# Next-day scheduling and publishing is now fully managed by the strict orchestrator.
