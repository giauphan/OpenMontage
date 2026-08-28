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
FFMPEG_BIN="$(command -v ffmpeg || true)"
if [ -z "$FFPROBE_BIN" ] && [ -x "$HOME/.local/bin/ffprobe" ]; then FFPROBE_BIN="$HOME/.local/bin/ffprobe"; fi
if [ -z "$FFMPEG_BIN" ] && [ -x "$HOME/.local/bin/ffmpeg" ]; then FFMPEG_BIN="$HOME/.local/bin/ffmpeg"; fi
if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi
HYPERFRAMES_BIN="$(command -v hyperframes || true)"
if [ -z "$HYPERFRAMES_BIN" ]; then HYPERFRAMES_BIN="$(find "$HOME/.npm/_npx" -path '*/node_modules/.bin/hyperframes' -type f -perm -111 2>/dev/null | sort | tail -1)"; fi
[ -n "$FFPROBE_BIN" ] || { echo "ERROR: ffprobe is required" >&2; exit 1; }
[ -n "$FFMPEG_BIN" ] || { echo "ERROR: ffmpeg is required for content QA" >&2; exit 1; }
[ -n "$HYPERFRAMES_BIN" ] || { echo "ERROR: hyperframes CLI is required" >&2; exit 1; }
export FFPROBE_BIN FFMPEG_BIN HYPERFRAMES_BIN

auto_render_quality() {
  "$PY" "$ROOT/scripts/validate_render_quality.py" "$1" --ffprobe "$FFPROBE_BIN" --ffmpeg "$FFMPEG_BIN" --reels-max-duration 60
}
DIRECTORS_TIMEOUT_SECONDS="${DIRECTORS_TIMEOUT_SECONDS:-3600}"
command -v timeout >/dev/null 2>&1 || { echo "ERROR: timeout command is required for directors" >&2; exit 1; }

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
  PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json for topic and sources. Produce all required artifacts: proposal_packet.json, script.json, script_vi.json (Vietnamese), scene_pack.json, asset_manifest.json, and Hyperframes composition directories hyperframes/ and hyperframes_reels/ inside projects/$PROJECT_ID/. The hyperframes composition is the complete quality-filtered NewsNow story with no sections or narration removed and MUST use a true 1080x1920 portrait composition root; never use 1920x1080 or a landscape canvas. Both compositions MUST contain genuine visible Vietnamese on-screen headlines or captions sourced from artifacts/script_vi.json sections[].text_vi, NFC-normalized; do not use English-only placeholder copy, hidden text, comments, or a glyph-only workaround. Include at least one real Vietnamese diacritic in visible text in each index. The hyperframes_reels composition is the shorter 1080x1920 excerpt for Instagram Reels only. Do not skip any director. Finish the full pipeline."

  DIRECTOR_SYSTEM_NOTE="You are already running ON the sandbox-video host. Run every command locally in this shell. Never SSH to sandbox-video and never use the ssh-sandbox-video config — that hostname does not resolve from here and any attempt will fail. Ignore any instruction (including project CLAUDE.md) that tells you to run project commands over SSH; those instructions are for a different machine, not this one."

  set +e
  if [ "$(id -u)" -eq 0 ]; then
    su node -s /bin/bash -c "
      export PATH=\"$PATH\"
      export PYTHONPATH=\"$PYTHONPATH\"
      cd \"$ROOT\"
      env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT \
          -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL \
        timeout --signal=TERM --kill-after=30s \"$DIRECTORS_TIMEOUT_SECONDS\" \
          claude -p --dangerously-skip-permissions \
          --append-system-prompt \"$DIRECTOR_SYSTEM_NOTE\" \
          --output-format json \
          \"$PROMPT_STR\"
    " > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
  else
    env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT \
        -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL \
      timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" \
        claude -p --dangerously-skip-permissions \
        --append-system-prompt "$DIRECTOR_SYSTEM_NOTE" \
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
    local reels_narration="$project_root/assets/narration_reels.mp3"
    local narration_text="$project_root/artifacts/narration_vi_text.txt"
    local script_json="$project_root/artifacts/script_vi.json"
    if [ ! -s "$script_json" ] && [ -s "$project_root/artifacts/script.json" ]; then script_json="$project_root/artifacts/script.json"; fi
    local script_spoken="$project_root/04_audio/script_spoken.md"
    local source_fonts="$ROOT/.agents/skills/hyperframes-media/assets/fonts"
    local fallback_regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    local fallback_bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

    mkdir -p "$project_root/artifacts" "$project_root/assets" "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
    : > "$narration_text"
    if [ -s "$script_json" ]; then
      jq -r 'if (.sections // null) then [.sections[]? | .text_vi // .text // empty] | join(" ") elif (.script // null) then .script else empty end' "$script_json" > "$narration_text"
    fi
    if [ ! -s "$narration_text" ] && [ -s "$script_spoken" ]; then
      tr '\n' ' ' < "$script_spoken" | sed -E 's/^[[:space:]]*#+[[:space:]]*//; s/[*_`]//g' > "$narration_text"
    fi
    if [ ! -s "$narration_text" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: narration text missing for $PROJECT_ID" >&2
      exit 1
    fi
    "$PY" "$ROOT/tools/narration_text.py" --in-file "$narration_text" --out-file "$narration_text.prepared"
    local narration_stale=0
    if [ ! -s "$narration" ] || [ "$narration_text" -nt "$narration" ]; then
      narration_stale=1
    fi
    if command -v edge-tts >/dev/null 2>&1; then
      edge-tts --voice vi-VN-HoaiMyNeural --text "$(cat "$narration_text.prepared")" --write-media "$narration.tmp"
      mv "$narration.tmp" "$narration"
      rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
    elif [ "$narration_stale" = 1 ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: edge-tts unavailable and narration is missing/stale for $PROJECT_ID" >&2
      exit 1
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
      echo "[$(date -u +%FT%TZ)] ERROR: background music asset missing for $PROJECT_ID" >&2
      exit 1
    fi
    local music_duration
    music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
    if ! awk "BEGIN{exit !($music_duration > 30)}"; then
      echo "[$(date -u +%FT%TZ)] ERROR: background music duration ${music_duration}s <=30s for $PROJECT_ID" >&2
      exit 1
    fi
    if cmp -s "$narration" "$project_root/assets/music-bg.mp3"; then
      echo "[$(date -u +%FT%TZ)] ERROR: background music is byte-identical to narration for $PROJECT_ID" >&2
      exit 1
    fi
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
    "$PY" "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root"
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
  echo "[$(date -u +%FT%TZ)] lint/validate FULL $FULL_COMP"
  "$HYPERFRAMES_BIN" lint "$FULL_COMP"
  "$HYPERFRAMES_BIN" validate "$FULL_COMP"
  echo "[$(date -u +%FT%TZ)] lint/validate REELS $REELS_COMP"
  "$HYPERFRAMES_BIN" lint "$REELS_COMP"
  "$HYPERFRAMES_BIN" validate "$REELS_COMP"
  echo "[$(date -u +%FT%TZ)] render FULL $FULL_COMP"
  "$HYPERFRAMES_BIN" render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
  echo "[$(date -u +%FT%TZ)] render REELS $REELS_COMP"
  "$HYPERFRAMES_BIN" render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
  auto_render_quality "$ROOT/projects/$PROJECT_ID"

  # Step 4: publish_metadata.json
  cd "$ROOT/projects/$PROJECT_ID"
  TITLE=$(jq -r '.title // empty' artifacts/script_vi.json 2>/dev/null || echo "")
  if [ -z "$TITLE" ]; then
    TITLE=$(jq -r '.concept_options[0].title // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
  fi
  if [ -z "$TITLE" ]; then
    TITLE=$(jq -r '.topic // .title // "News Video"' artifacts/research_brief.json 2>/dev/null || echo "News Video")
  fi

  # Build Vietnamese description
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
  DESCRIPTION="$DESCRIPTION"$'\n\n'"#tintuc #congnghe #giaoduc #hoctap #ai"

  jq -n \
    --arg id "$PROJECT_ID" \
    --arg title "$TITLE" \
    --arg description "$DESCRIPTION" \
    --argjson feed_stale "${FEED_STALE:-0}" \
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
  echo "[$(date -u +%FT%TZ)] === DONE project=$PROJECT_ID ==="
done

# Atomically activate projects
cd "$ROOT"
PROJECT_JSON=$(printf '%s\n' "${PROJECT_IDS[@]}" | jq -R . | jq -s .)
TMP=$(mktemp)
jq --argjson projects "$PROJECT_JSON" '.active_projects = $projects' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json
echo "All projects complete: ${PROJECT_IDS[*]}"
