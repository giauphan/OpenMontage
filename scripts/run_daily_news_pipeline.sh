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

export PATH="/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:$PATH"
export PYTHONPATH="$ROOT"

if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi

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
  if [ -d "projects/$PROJECT_ID" ]; then
    chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true
  fi
  echo "[$(date -u +%FT%TZ)] PROJECT_ID=$PROJECT_ID"

# Step 2.5: Run Directors pipeline via Claude CLI (unattended, logged) (P2)
DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"
START_TS=$(date -u +%s)

echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"

DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_result.json"

set +e
PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json, then execute Proposal -> Script -> Scene -> Asset -> Compose directors in sequence. Generate hyperframes/index.html and hyperframes_reels/index.html under projects/$PROJECT_ID/. Let content determine duration with no upper limit, but both compositions must exceed 30 seconds. Use Vietnamese narration with a strong first-3-second hook, fast pacing, no dead air, and synchronized dynamic captions. Do not ask for confirmation between stages."

if [ "$(id -u)" -eq 0 ]; then
  su node -s /bin/bash -c "
    export PATH=\"$PATH\"
    export PYTHONPATH=\"$PYTHONPATH\"
    cd \"$ROOT\"
    env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT \
        -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL \
      claude -p --dangerously-skip-permissions \
        --output-format json \
        \"$PROMPT_STR\"
  " > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
else
  env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT \
      -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL \
    claude -p --dangerously-skip-permissions \
      --output-format json \
      "$PROMPT_STR" \
      > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
fi
CLAUDE_EXIT=$?
set -e

if jq empty "$DIRECTORS_JSON" 2>/dev/null; then
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

if [ $CLAUDE_EXIT -eq 0 ]; then
  echo "[$(date -u +%FT%TZ)] directors OK project=$PROJECT_ID exit=0 elapsed=${ELAPSED}s" \
    >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  # Check if composition files exist
  HYPER_FULL=$(find "$ROOT/projects/$PROJECT_ID" -iwholename "*hyperframes/index.html" 2>/dev/null | head -n 1)
  if [ -n "$HYPER_FULL" ] || [ -f "$ROOT/projects/$PROJECT_ID/hyperframes/index.html" ]; then
    echo "[$(date -u +%FT%TZ)] artifacts OK" >> "$ROOT/logs/directors_${PROJECT_ID}.log"
  else
    echo "[$(date -u +%FT%TZ)] WARN: claude exit=0 but expected index.html missing" \
      >> "$ROOT/logs/directors_${PROJECT_ID}.log"
    CLAUDE_EXIT=2
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
  local narration_text="$project_root/artifacts/narration_vi_text.txt"
  local source_fonts="$ROOT/.agents/skills/hyperframes-media/assets/fonts"
  local fallback_regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
  local fallback_bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

  mkdir -p "$project_root/assets" "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
  local narration_duration=0
  if [ -s "$narration" ]; then
    narration_duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  fi
  if [ -s "$narration_text" ] && command -v edge-tts >/dev/null 2>&1 && awk "BEGIN{exit !($narration_duration <= 30)}"; then
    edge-tts --voice vi-VN-HoaiMyNeural --text "$(tr '\n' ' ' < "$narration_text")" --write-media "$narration"
  fi
  if [ ! -s "$narration" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration asset missing for $PROJECT_ID"
    exit 1
  fi
  narration_duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
  if ! awk "BEGIN{exit !($narration_duration > 30)}"; then
    echo "[$(date -u +%FT%TZ)] ERROR: narration duration ${narration_duration}s <=30s for $PROJECT_ID"
    exit 1
  fi
  if [ ! -s "$project_root/assets/music-bg.mp3" ]; then
    cp "$narration" "$project_root/assets/music-bg.mp3"
  fi
  local music_duration
  music_duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
  if ! awk "BEGIN{exit !($music_duration > 30)}"; then
    cp "$narration" "$project_root/assets/music-bg.mp3"
  fi
  for composition in hyperframes hyperframes_reels; do
    local target="$project_root/$composition/assets"
    cp "$narration" "$target/narration.mp3"
    cp "$project_root/assets/music-bg.mp3" "$target/music-bg.mp3"
    [ -s "$source_fonts/BeVietnamPro-Regular.ttf" ] && cp "$source_fonts/BeVietnamPro-Regular.ttf" "$target/BeVietnamPro-Regular.ttf" || cp "$fallback_regular" "$target/BeVietnamPro-Regular.ttf"
    [ -s "$source_fonts/BeVietnamPro-Bold.ttf" ] && cp "$source_fonts/BeVietnamPro-Bold.ttf" "$target/BeVietnamPro-Bold.ttf" || cp "$fallback_bold" "$target/BeVietnamPro-Bold.ttf"
    [ -s "$source_fonts/BeVietnamPro-ExtraBold.ttf" ] && cp "$source_fonts/BeVietnamPro-ExtraBold.ttf" "$target/BeVietnamPro-ExtraBold.ttf" || cp "$fallback_bold" "$target/BeVietnamPro-ExtraBold.ttf"
  done
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

if [ -n "$FULL_COMP" ] && [ ! -f "renders/final_full_vi_9x16.mp4" ]; then
  hyperframes render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
fi
if [ -n "$REELS_COMP" ] && [ ! -f "renders/final_reels_vi_9x16.mp4" ]; then
  hyperframes render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
fi

# Both required outputs must exist, exceed 30s, and carry an audio stream.
require_video() {
  local path="$1"
  if [ ! -s "$path" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: $path missing or empty for $PROJECT_ID"
    exit 1
  fi
  local dur
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$path" 2>/dev/null || echo 0)
  if ! awk "BEGIN{exit !($dur > 30)}"; then
    echo "[$(date -u +%FT%TZ)] ERROR: $path duration ${dur}s not > 30s for $PROJECT_ID"
    exit 1
  fi
  if [ -z "$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$path" 2>/dev/null)" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: $path has no audio stream for $PROJECT_ID"
    exit 1
  fi
}
require_video "renders/final_full_vi_9x16.mp4"
require_video "renders/final_reels_vi_9x16.mp4"

if [ "$FEED_STALE" -eq 1 ]; then
  echo "[$(date -u +%FT%TZ)] NOTICE: Render completed using STALE feed data."
fi

# Step 4: Create publish_metadata.json
TITLE=""
SUMMARY=""
if [ -f "artifacts/research_brief.json" ]; then
  TITLE=$(jq -r '.topic // .title // ""' artifacts/research_brief.json 2>/dev/null || echo "")
  SUMMARY=$(jq -r '.summary // ""' artifacts/research_brief.json 2>/dev/null || echo "")
fi

jq -n \
  --arg id "$PROJECT_ID" \
  --arg title "${TITLE:-News Video}" \
  --arg description "${SUMMARY:-AI generated news breakdown}" \
  --argjson feed_stale "$FEED_STALE" \
  '{
    id: $id,
    topic: $title,
    title: $title,
    description: $description,
    yt_shorts: "renders/final_full_vi_9x16.mp4",
    fb_video: "renders/final_full_vi_9x16.mp4",
    ig_reels: "renders/final_reels_vi_9x16.mp4",
    feed_stale: $feed_stale
  }' > publish_metadata.json

# Step 4.5: Run copyright preflight (if files exist)
if [ -f "renders/final_full_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_full_vi_9x16.mp4" || true
fi
if [ -f "renders/final_reels_vi_9x16.mp4" ]; then
  "$PY" "$ROOT/scripts/check_copyright.py" "renders/final_reels_vi_9x16.mp4" || true
fi

done

# Step 5: Atomically activate all three projects.
cd "$ROOT"
PROJECT_JSON=$(printf '%s\n' "${PROJECT_IDS[@]}" | jq -R . | jq -s .)
TMP=$(mktemp)
jq --argjson projects "$PROJECT_JSON" '.active_projects = $projects' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json

echo "Daily pipeline completed: ${PROJECT_IDS[*]} (Feed stale: $FEED_STALE)"
