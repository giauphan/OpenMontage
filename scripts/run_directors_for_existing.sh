#!/usr/bin/env bash
# Run directors + render for pre-initialized projects (bypasses selection stage).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$ROOT"
mkdir -p "$ROOT/logs"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
export PATH="/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:$PATH"
if [ -d "$HOME/.npm/_npx/702923228c2ce1e6/node_modules/.bin" ]; then
  export PATH="$HOME/.npm/_npx/702923228c2ce1e6/node_modules/.bin:$PATH"
fi
export PYTHONPATH="$ROOT"
FFPROBE_BIN="$(command -v ffprobe || true)"
if [ -z "$FFPROBE_BIN" ] && [ -x "$HOME/.local/bin/ffprobe" ]; then FFPROBE_BIN="$HOME/.local/bin/ffprobe"; fi
HYPERFRAMES_BIN="$(command -v hyperframes || true)"
if [ -z "$HYPERFRAMES_BIN" ]; then HYPERFRAMES_BIN="$(find "$HOME/.npm/_npx" -path '*/node_modules/.bin/hyperframes' -type f -perm -111 2>/dev/null | sort | tail -1)"; fi
[ -n "$FFPROBE_BIN" ] || { echo "ERROR: ffprobe is required" >&2; exit 1; }
[ -n "$HYPERFRAMES_BIN" ] || { echo "ERROR: hyperframes CLI is required" >&2; exit 1; }
export FFPROBE_BIN HYPERFRAMES_BIN

auto_render_quality() {
  "$PY" "$ROOT/scripts/validate_render_quality.py" "$1" --ffprobe "$FFPROBE_BIN"
}
if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi

PROJECT_IDS=("$@")
if [ "${#PROJECT_IDS[@]}" -eq 0 ]; then
  echo "Usage: $0 <project_id> [project_id ...]"
  exit 1
fi

for PROJECT_ID in "${PROJECT_IDS[@]}"; do
  cd "$ROOT"
  echo "[$(date -u +%FT%TZ)] === START project=$PROJECT_ID ==="
  if [ ! -d "projects/$PROJECT_ID" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: projects/$PROJECT_ID does not exist"
    exit 1
  fi
  chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true

  # Step 2.5: Directors
  DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"
  DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_result.json"
  START_TS=$(date -u +%s)
  echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"
  PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json for topic and sources. Produce all required artifacts: proposal_packet.json, script.json, script_vi.json (Vietnamese), scene_pack.json, asset_manifest.json, and Hyperframes composition directories hyperframes/ and hyperframes_reels/ inside projects/$PROJECT_ID/. Do not skip any director. Finish the full pipeline."

  set +e
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

  END_TS=$(date -u +%s)
  ELAPSED=$((END_TS - START_TS))

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

  if [ $CLAUDE_EXIT -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] directors OK project=$PROJECT_ID elapsed=${ELAPSED}s" | tee -a "$DIRECTORS_LOG"
  else
    echo "[$(date -u +%FT%TZ)] directors FAIL project=$PROJECT_ID exit=$CLAUDE_EXIT elapsed=${ELAPSED}s" | tee -a "$DIRECTORS_LOG"
    exit $CLAUDE_EXIT
  fi

  # Step 3: Render
  cd "$ROOT/projects/$PROJECT_ID"
  chmod -R 777 . 2>/dev/null || true
  mkdir -p renders

  materialize_hyperframes_assets() {
    local project_root="$1"
    local narration="$project_root/assets/narration.mp3"
    local narration_text="$project_root/artifacts/narration_vi_text.txt"
    local script_json="$project_root/artifacts/script_vi.json"
    if [ ! -s "$script_json" ] && [ -s "$project_root/artifacts/script.json" ]; then script_json="$project_root/artifacts/script.json"; fi
    local script_spoken="$project_root/04_audio/script_spoken.md"
    local source_fonts="$ROOT/.agents/skills/hyperframes-media/assets/fonts"
    local fallback_regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    local fallback_bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

    mkdir -p "$project_root/assets" "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
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
    if [ -s "$narration_text" ] && command -v edge-tts >/dev/null 2>&1 && awk "BEGIN{exit !($narration_duration <= 30)}"; then
      edge-tts --voice vi-VN-HoaiMyNeural --text "$(tr '\\n' ' ' < "$narration_text")" --write-media "$narration"
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
      cp "$narration" "$project_root/assets/music-bg.mp3"
    fi
    local music_duration
    music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
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
    python3 "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root"
  }
  materialize_hyperframes_assets "$ROOT/projects/$PROJECT_ID"

  FULL_COMP=""

  if [ -d "hyperframes" ]; then FULL_COMP="hyperframes"
  elif [ -d "Hyperframes" ]; then FULL_COMP="Hyperframes"
  fi
  REELS_COMP=""
  if [ -d "hyperframes_reels" ]; then REELS_COMP="hyperframes_reels"
  elif [ -d "Hyperframes_reels" ]; then REELS_COMP="Hyperframes_reels"
  fi

  if [ -z "$FULL_COMP" ] || [ -z "$REELS_COMP" ] || [ ! -f "$FULL_COMP/index.html" ] || [ ! -f "$REELS_COMP/index.html" ]; then
    echo "[$(date -u +%FT%TZ)] ERROR: both HyperFrames composition index files are required for $PROJECT_ID"
    exit 1
  fi
  rm -f renders/final_full_vi_9x16.mp4 renders/final_reels_vi_9x16.mp4
  echo "[$(date -u +%FT%TZ)] render FULL $FULL_COMP"
  "$HYPERFRAMES_BIN" render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
  echo "[$(date -u +%FT%TZ)] render REELS $REELS_COMP"
  "$HYPERFRAMES_BIN" render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
  auto_render_quality "$ROOT/projects/$PROJECT_ID"

  # Step 4: publish_metadata.json
  cd "$ROOT/projects/$PROJECT_ID"
  TITLE=$(jq -r '.topic // .title // ""' artifacts/research_brief.json 2>/dev/null || echo "")
  SUMMARY=$(jq -r '.summary // ""' artifacts/research_brief.json 2>/dev/null || echo "")
  jq -n \
    --arg id "$PROJECT_ID" \
    --arg title "${TITLE:-News Video}" \
    --arg description "${SUMMARY:-AI generated news breakdown}" \
    '{
      id: $id,
      topic: $title,
      title: $title,
      description: $description,
      yt_shorts: "renders/final_full_vi_9x16.mp4",
      fb_video: "renders/final_full_vi_9x16.mp4",
      ig_reels: "renders/final_reels_vi_9x16.mp4",
      feed_stale: false
    }' > publish_metadata.json
  echo "[$(date -u +%FT%TZ)] === DONE project=$PROJECT_ID ==="
done

# Atomically activate projects
cd "$ROOT"
PROJECT_JSON=$(printf '%s\n' "${PROJECT_IDS[@]}" | jq -R . | jq -s .)
TMP=$(mktemp)
jq --argjson projects "$PROJECT_JSON" '.active_projects = $projects' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json
echo "All projects complete: ${PROJECT_IDS[*]}"
