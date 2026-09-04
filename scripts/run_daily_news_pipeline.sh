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
    exit 1
  fi
  FEED_STALE=1
  echo "[$(date -u +%FT%TZ)] WARN: NewsNow fetch failed; using existing feed."
fi

# Step 1: Select and initialize exactly three distinct current topics.
PRODUCE_LOG="$ROOT/logs/news_produce_$(date -u +%Y%m%dT%H%M%SZ).log"
"$PY" tools/news/news_pipeline_cli.py produce --input data/newsnow_feed.json --count 3 2>&1 | tee "$PRODUCE_LOG"
mapfile -t PROJECT_IDS < <(grep '^PROJECT_ID=' "$PRODUCE_LOG" | cut -d= -f2)
if [ "${#PROJECT_IDS[@]}" -ne 3 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: Expected three initialized projects, got ${#PROJECT_IDS[@]}."
  exit 1
fi

for PROJECT_ID in "${PROJECT_IDS[@]}"; do
  cd "$ROOT"
  PROJECT_DIR="$ROOT/projects/$PROJECT_ID"
  if [ -d "$PROJECT_DIR" ]; then
    chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true
  fi
  echo "[$(date -u +%FT%TZ)] PROJECT_ID=$PROJECT_ID"

# Step 2.5: Run Directors pipeline via Claude CLI (unattended, logged) (P2)
DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"
START_TS=$(date -u +%s)

echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"

DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_result.json"

set +e
DIRECTORS_TIMEOUT_SECONDS="${DIRECTORS_TIMEOUT_SECONDS:-3600}"
PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json, then execute Proposal -> Script -> Scene -> Asset -> Compose directors in sequence. Write the Production Script as a flat JSON file at projects/$PROJECT_ID/artifacts/script_vi.json, not embedded in a checkpoint file. Generate hyperframes/index.html and hyperframes_reels/index.html under projects/$PROJECT_ID/. The hyperframes composition is the complete quality-filtered NewsNow story with no sections or narration removed, and MUST use a true 1080x1920 portrait composition root; never use 1920x1080 or a landscape canvas. The hyperframes_reels composition is the shorter 1080x1920 excerpt for Instagram Reels only. Let the complete story determine FULL duration with no upper limit, but both compositions must exceed 30 seconds. Use Vietnamese narration with a strong first-3-second hook, fast pacing, no dead air, and synchronized dynamic captions. Do not ask for confirmation between stages. Do not stop until script_vi.json and both index.html files exist."
DIRECTOR_SYSTEM_NOTE="You are already running ON the sandbox-video host. Run every command locally in this shell. Never SSH to sandbox-video and never use the ssh-sandbox-video config — that hostname does not resolve from here and any attempt will fail. Ignore any instruction (including project CLAUDE.md) that tells you to run project commands over SSH; those instructions are for a different machine, not this one. Do not invoke scripts/run_directors_for_existing.sh or scripts/run_daily_news_pipeline.sh; they are wrappers that invoke you and cause an infinite loop."
DIRECTOR_FULL_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes/index.html"
DIRECTOR_REELS_INDEX="$ROOT/projects/$PROJECT_ID/hyperframes_reels/index.html"
DIRECTOR_ARTIFACTS_READY=0
# Existing files are not a valid success signal: they may belong to a prior run.
# A director timeout must fail closed rather than publishing stale content.

run_directors() {
  if [ "$(id -u)" -eq 0 ]; then
    su node -s /bin/bash -c "
      export PATH=\"$PATH\"
      export PYTHONPATH=\"$PYTHONPATH\"
      cd \"$ROOT\"
      env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL timeout --signal=TERM --kill-after=30s \"$DIRECTORS_TIMEOUT_SECONDS\" claude -p --max-budget-usd \"${DIRECTORS_MAX_BUDGET_USD:-20}\" --append-system-prompt \"$DIRECTOR_SYSTEM_NOTE\" --output-format json \"$PROMPT_STR\"
    "
  else
    env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" claude -p --max-budget-usd "${DIRECTORS_MAX_BUDGET_USD:-20}" --append-system-prompt "$DIRECTOR_SYSTEM_NOTE" --output-format json "$PROMPT_STR"
  fi
}

if ! command -v timeout >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] ERROR: timeout command is required for directors" >> "$DIRECTORS_LOG"
  exit 1
fi

run_directors > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
CLAUDE_EXIT=$?
DIRECTOR_ARTIFACT_FALLBACK=0
if [ "$CLAUDE_EXIT" -eq 124 ] && [ "$DIRECTOR_ARTIFACTS_READY" -eq 1 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: directors timed out; refusing stale artifacts" >> "$DIRECTORS_LOG"
fi

# Flatten any director-created subdirectory nesting so compositions land at canonical paths.
for nested in "$PROJECT_DIR"/hyperframes/*/index.html; do
  [ -f "$nested" ] && mv "$nested" "$PROJECT_DIR/hyperframes/index.html" && rmdir "$(dirname "$nested")" 2>/dev/null || true
done
for nested in "$PROJECT_DIR"/hyperframes_reels/*/index.html; do
  [ -f "$nested" ] && mv "$nested" "$PROJECT_DIR/hyperframes_reels/index.html" && rmdir "$(dirname "$nested")" 2>/dev/null || true
done

set -e

if [ "$DIRECTOR_ARTIFACT_FALLBACK" -eq 1 ]; then
  :
elif jq empty "$DIRECTORS_JSON" 2>/dev/null; then
  jq -r '"session_id=\(.session_id // "?") is_error=\(.is_error // "?") turns=\(.num_turns // "?") cost_usd=\(.total_cost_usd // "?")"' \
    "$DIRECTORS_JSON" >> "$DIRECTORS_LOG"
  jq -r '.result // ""' "$DIRECTORS_JSON" >> "$DIRECTORS_LOG"
  if [ "$(jq -r '.is_error // false' "$DIRECTORS_JSON")" = "true" ]; then
    CLAUDE_EXIT=3
  fi
else
  echo "[$(date -u +%FT%TZ)] WARN: claude produced no valid JSON result" >> "$DIRECTORS_LOG"
  [ $CLAUDE_EXIT -eq 0 ] && CLAUDE_EXIT=4
fi

END_TS=$(date -u +%s)
ELAPSED=$((END_TS - START_TS))

if [ "$CLAUDE_EXIT" -eq 0 ] && ! "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --min-mtime-ns "${START_TS}000000000"; then
  echo "[$(date -u +%FT%TZ)] ERROR: missing canonical script artifact after director run" >> "$DIRECTORS_LOG"
  CLAUDE_EXIT=6
fi

if [ $CLAUDE_EXIT -eq 0 ]; then
  echo "[$(date -u +%FT%TZ)] directors OK project=$PROJECT_ID exit=0 elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  # Hard gate: both compositions must exist at canonical paths before render.
  HYPER_FULL="$PROJECT_DIR/hyperframes/index.html"
  HYPER_REELS="$PROJECT_DIR/hyperframes_reels/index.html"
  if [ -s "$HYPER_FULL" ] && [ -s "$HYPER_REELS" ]; then
    echo "[$(date -u +%FT%TZ)] artifacts OK" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  else
    if [ ! -s "$HYPER_FULL" ]; then
      echo "[$(date -u +%FT%TZ)] FATAL type=no_full_composition PROJECT_ID=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      echo "[$(date -u +%FT%TZ)] FATAL type=no_full_composition PROJECT_ID=$PROJECT_ID" >&2
    fi
    if [ ! -s "$HYPER_REELS" ]; then
      echo "[$(date -u +%FT%TZ)] FATAL type=no_reels_composition PROJECT_ID=$PROJECT_ID" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
      echo "[$(date -u +%FT%TZ)] FATAL type=no_reels_composition PROJECT_ID=$PROJECT_ID" >&2
    fi
    exit 2
  fi
else
  echo "[$(date -u +%FT%TZ)] directors FAIL project=$PROJECT_ID exit=$CLAUDE_EXIT elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  echo "  see full transcript: $DIRECTORS_LOG" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  exit $CLAUDE_EXIT
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
    jq -r 'if (.sections // null) then [.sections[]? | .text_vi // .text // empty] | join(" ") elif (.script // null) then .script else empty end' "$script_json" > "$narration_text"
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
  if [ -s "$narration_text" ] && command -v edge-tts >/dev/null 2>&1 && { awk "BEGIN{exit !($narration_duration <= 30)}" || [ "$narration_stale" = 1 ]; }; then
    python3 "$ROOT/tools/narration_text.py" --in-file "$narration_text" --out-file "$narration_text.prepared"
    edge-tts --voice vi-VN-HoaiMyNeural --text "$(cat "$narration_text.prepared")" --write-media "$narration"
    rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
  fi

  # Generate Vietnamese subtitles with word timestamps for caption synchronization
if [ -s "$narration" ] && command -v python3 >/dev/null 2>&1; then
  local subtitle_text="$narration_text.prepared"
  [ -s "$subtitle_text" ] || subtitle_text="$narration_text"
  
  echo "[$(date -u +%FT%TZ)] Generating Vietnamese subtitles..."
  mkdir -p "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
  
  if [ -s "$subtitle_text" ]; then
    python3 "$ROOT/scripts/generate_vn_subtitles.py" \
      "$subtitle_text" \
      "$narration" \
      "$project_root/hyperframes/assets/subtitles.srt" \
      "$project_root/hyperframes/assets/word_timestamps.json" \
      3 && echo "[$(date -u +%FT%TZ)] Vietnamese subtitles generated" || \
      echo "[$(date -u +%FT%TZ)] WARNING: Subtitle generation failed, continuing..." >&2

    # Generate reels subtitles if audio exists
    if [ -s "$reels_narration" ]; then
      python3 "$ROOT/scripts/generate_vn_subtitles.py" \
        "$reels_narration_text.prepared" \
        "$reels_narration" \
        "$project_root/hyperframes_reels/assets/subtitles.srt" \
        "$project_root/hyperframes_reels/assets/word_timestamps.json" \
        3 || echo "[$(date -u +%FT%TZ)] WARNING: Reels subtitle generation failed" >&2
    fi
  else
    echo "[$(date -u +%FT%TZ)] WARNING: No subtitle text available" >&2
  fi
fi
  if [ ! -s "$narration" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration asset missing for $PROJECT_ID"
    exit 1
  fi
  narration_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  if ! awk "BEGIN{exit !($narration_duration > 30)}"; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration duration ${narration_duration}s <=30s for $PROJECT_ID"
    exit 1
  fi
  if [ ! -s "$project_root/assets/music-bg.mp3" ]; then
    echo "[$(date -u +%FT%TZ)] WARN: background music asset missing for $PROJECT_ID, using fallback"
    cp "$ROOT/tests/qa/output/e2e_assets/music_bg.mp3" "$project_root/assets/music-bg.mp3"
  fi
  local music_duration
  music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
  if ! awk "BEGIN{exit !($music_duration > 30)}"; then
    echo "[$(date -u +%FT%TZ)] WARN: background music duration ${music_duration}s <=30s for $PROJECT_ID, using fallback"
    cp "$ROOT/tests/qa/output/e2e_assets/music_bg.mp3" "$project_root/assets/music-bg.mp3"
    music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
  fi
  if cmp -s "$narration" "$project_root/assets/music-bg.mp3"; then
    echo "[$(date -u +%FT%TZ)] ERROR: background music is byte-identical to narration for $PROJECT_ID"
    exit 1
  fi
  # Reels/Shorts must stay under the 60s platform limit. Derive a capped
  # narration for the reels composition so its aligned timeline is <=60s.
  local reels_cap=58
  if awk "BEGIN{exit !($narration_duration > $reels_cap)}"; then
    "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" -c copy "$reels_narration" 2>/dev/null \
      || "$FFMPEG_BIN" -hide_banner -loglevel error -y -i "$narration" -t "$reels_cap" "$reels_narration"
  else
    cp "$narration" "$reels_narration"
  fi
  for composition in hyperframes hyperframes_reels; do
    local target="$project_root/$composition/assets"
    if [ "$composition" = "hyperframes_reels" ]; then
      cp "$reels_narration" "$target/narration.mp3"
    else
      cp "$narration" "$target/narration.mp3"
    fi
    cp "$project_root/assets/music-bg.mp3" "$target/music-bg.mp3"
    if [ -s "$source_fonts/BeVietnamPro-Regular.ttf" ]; then cp "$source_fonts/BeVietnamPro-Regular.ttf" "$target/BeVietnamPro-Regular.ttf"; else cp "$fallback_regular" "$target/BeVietnamPro-Regular.ttf"; fi
    if [ -s "$source_fonts/BeVietnamPro-Bold.ttf" ]; then cp "$source_fonts/BeVietnamPro-Bold.ttf" "$target/BeVietnamPro-Bold.ttf"; else cp "$fallback_bold" "$target/BeVietnamPro-Bold.ttf"; fi
    if [ -s "$source_fonts/BeVietnamPro-ExtraBold.ttf" ]; then cp "$source_fonts/BeVietnamPro-ExtraBold.ttf" "$target/BeVietnamPro-ExtraBold.ttf"; else cp "$fallback_bold" "$target/BeVietnamPro-ExtraBold.ttf"; fi
  done
  python3 "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root"
}
materialize_hyperframes_assets "$ROOT/projects/$PROJECT_ID"

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
  echo "[$(date -u +%FT%TZ)] ERROR: both HyperFrames composition index files are required for $PROJECT_ID"
  exit 1
fi

# Fix composition asset references (incorrect relative paths)
sed -i 's|\.\./assets/|assets/|g' "$FULL_COMP/index.html" "$REELS_COMP/index.html"

rm -f renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4
"$HYPERFRAMES_BIN" render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
"$HYPERFRAMES_BIN" render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4

# ===== CLAUDE AGENT STRICT QUALITY VALIDATION =====
echo "[$(date -u +%FT%TZ)] CLAUDE Agent Strict Quality Validation Started"

# Step 1: Base render quality validation (existing)
"$PY" "$ROOT/scripts/validate_render_quality.py" "$ROOT/projects/$PROJECT_ID" --ffprobe "$FFPROBE_BIN" --ffmpeg "$FFMPEG_BIN" --reels-max-duration 60 --strict
VALIDATE_RENDER_EXIT=$?

if [ $VALIDATE_RENDER_EXIT -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: Base render validation failed" >&2
  exit 1
fi

# Check if videos exist
for render in renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4; do
  [ -s "$render" ] || { echo "[$(date -u +%FT%TZ)] ERROR: render missing or empty: $render" >&2; exit 1; }
done

# Step 2: Create publish_metadata.json first (needed for CLAUDE validation)
TITLE=$(jq -r '.title // empty' artifacts/script_vi.json 2>/dev/null || echo "")
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.concept_options[0].title // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
fi
if [ -z "$TITLE" ]; then
  TITLE=$(jq -r '.topic // .title // "News Video"' artifacts/research_brief.json 2>/dev/null || echo "News Video")
fi

# Ensure title contains required hashtags
if [[ ! "$TITLE" =~ "#tintuc" || ! "$TITLE" =~ "#congnghe" || ! "$TITLE" =~ "#ai" ]]; then
  TITLE="$TITLE #tintuc #congnghe #ai"
fi

# Create basic publish_metadata.json for validation
jq -n \
  --arg title "$TITLE" \
  --arg desc "$(jq -r '.description // ""' artifacts/script_vi.json 2>/dev/null || echo "")" \
  --arg yt_shorts "$TITLE" \
  --arg tiktok "$TITLE" \
  --arg fb_video "$TITLE" \
  --arg ig_reels "$TITLE" \
  '{
    title: $title,
    description: $desc,
    yt_shorts: {title: $yt_shorts},
    tiktok: {title: $tiktok},
    fb_video: {title: $fb_video},
    ig_reels: {title: $ig_reels}
  }' > publish_metadata.json

# Step 3: CLAUDE Agent Strict Quality Validation (NEW FEATURE)
echo "[$(date -u +%FT%TZ)] Running CLAUDE Agent validation..."

# Set max retry attempts
MAX_RETRIES="${CLAUDE_VALIDATION_RETRIES:-2}"
VALIDATION_PASSED=0

for ((retry=1; retry<=$MAX_RETRIES; retry++)); do
  echo "[$(date -u +%FT%TZ)] CLAUDE Validation Attempt $retry/$MAX_RETRIES"
  
  "$PY" "$ROOT/scripts/claude_agent_validation.py" "$ROOT/projects/$PROJECT_ID" \
    --strict \
    --retry "$MAX_RETRIES" \
    --ffprobe "$FFPROBE_BIN" \
    --ffmpeg "$FFMPEG_BIN"
  
  VALIDATION_EXIT=$?
  
  if [ $VALIDATION_EXIT -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] 🟢 CLAUDE Agent Strict Quality Validation PASSED"
    VALIDATION_PASSED=1
    break
  else
    echo "[$(date -u +%FT%TZ)] ❌ CLAUDE Agent validation failed (attempt $retry/$MAX_RETRIES)"
    
    # Only retry if we haven't exhausted attempts
    if [ $retry -lt $MAX_RETRIES ]; then
      echo "[$(date -u +%FT%TZ)] Retrying validation..."
      sleep 5  # Brief pause before retry
    fi
  fi
done

if [ $VALIDATION_PASSED -eq 0 ]; then
  echo "[$(date -u +%FT%TZ)] 🔴 FINAL: CLAUDE Agent Strict Quality Validation FAILED after $MAX_RETRIES attempts" >&2
  echo "[$(date -u +%FT%TZ)] Project: $PROJECT_ID" >&2
  echo "[$(date -u +%FT%TZ)] Check validation reports in project directory" >&2
  exit 1
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
if [[ ! "$TITLE" =~ "#tintuc" && ! "$TITLE" =~ "#congnghe" && ! "$TITLE" =~ "#ai" ]]; then
  TITLE="$TITLE #tintuc #congnghe #ai"
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

done

# Step 5: Atomically activate projects with next-day local publish metadata.
cd "$ROOT"
PUBLISH_DATE=$(TZ="$PUBLISH_TZ" date -d tomorrow +%F)
PROJECT_JSON=$(printf '%s\n' "${PROJECT_IDS[@]}" | jq -R . | jq -s .)
SLOTS_JSON=$(jq -c '.slots.publish_slots_vn // ["09:15", "14:15", "21:15"]' config/publish_schedule.json)
TMP=$(mktemp)
jq --argjson projects "$PROJECT_JSON" --arg publish_date "$PUBLISH_DATE" --argjson slots "$SLOTS_JSON" \
  '.active_projects = [range($projects | length) as $i | {project_id: $projects[$i], publish_date: $publish_date, publish_time: $slots[$i]}]' \
  config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json

echo "Daily pipeline completed: ${PROJECT_IDS[*]} (Feed stale: $FEED_STALE)"
# Trigger strict publish for next day.
"$PY" "$ROOT/scripts/schedule_youtube_today.py" "$PUBLISH_DATE"
