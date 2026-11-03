#!/usr/bin/env bash
# Run directors + render for pre-initialized projects (bypasses selection stage).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$ROOT"
mkdir -p "$ROOT/logs"
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
export PATH="$HOME/.local/share/uv/tools/edge-tts/bin:/app/node_modules/.bin:$ROOT/node_modules/.bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$ROOT"
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
export FFPROBE_BIN FFMPEG_BIN HYPERFRAMES_BIN

auto_render_quality() {
  "$PY" "$ROOT/scripts/validate_render_quality.py" "$1" --ffprobe "$FFPROBE_BIN" --ffmpeg "$FFMPEG_BIN" --min-duration 60.0 --reels-max-duration 180.0
}
if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi
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
  if [ "${SKIP_DIRECTORS:-0}" = "1" ]; then
    "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID"
    [ -s "$ROOT/projects/$PROJECT_ID/hyperframes/index.html" ] || { echo "ERROR: missing full composition for $PROJECT_ID" >&2; exit 1; }
    [ -s "$ROOT/projects/$PROJECT_ID/hyperframes_reels/index.html" ] || { echo "ERROR: missing Reels composition for $PROJECT_ID" >&2; exit 1; }
    echo "[$(date -u +%FT%TZ)] directors SKIPPED project=$PROJECT_ID validated_existing_artifacts=1"
  else
  RUN_ID="${RUN_NONCE:-$(date -u +%Y%m%dT%H%M%S%NZ)}"
  DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_${RUN_ID}.log"
  DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_${RUN_ID}_result.json"
  START_TS=$(date -u +%s)
  echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"
  PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json for topic and sources. Produce all required artifacts: proposal_packet.json, script.json, script_vi.json (Vietnamese), scene_pack.json, asset_manifest.json, and Hyperframes composition directories hyperframes/ and hyperframes_reels/ inside projects/$PROJECT_ID/. Write the script artifacts as flat JSON files under artifacts/, not embedded inside checkpoints. Ensure 100% correct Vietnamese spelling, exact grammatical tone marks, and correct technical terminology in all scripts and on-screen text (e.g. \"PHẦN CỨNG\" not \"PHÂN CỨNG\", \"KHÔNG CẦN\" not \"KHÔNG CÂN\"). The hyperframes composition is the complete quality-filtered NewsNow story with no sections or narration removed and MUST use a true 1080x1920 portrait composition root; never use 1920x1080 or a landscape canvas. Never use fixed width or height on text containers like highlight boxes, badges, or title cards; always use CSS width: fit-content; max-width: 90vw; word-break: break-word; box-sizing: border-box; display: inline-block; padding: 10px 20px; so Vietnamese text does not overflow or misalign. Both compositions MUST contain genuine visible Vietnamese on-screen headlines or captions sourced from artifacts/script_vi.json sections[].text_vi, NFC-normalized; do not use English-only placeholder copy, hidden text, comments, or a glyph-only workaround. Include at least one real Vietnamese diacritic in visible text in each index. The hyperframes_reels composition is the shorter 1080x1920 excerpt for Instagram Reels only. For both compositions, create one finite gsap.timeline({paused:true}), put every animation including scene opacity changes on it, then register the fully constructed timeline synchronously at window.__timelines['main']. Never use standalone gsap.to/from/fromTo/set, repeat:-1, timers, async timeline construction, or read/set tl.duration() before all children are added. Preserve exact script section start times with explicit timeline positions. Motion must be purposeful and content-led; do not add decorative motion solely to evade the frozen-canvas check. Do not skip any director. Finish the full pipeline."

  DIRECTOR_SYSTEM_NOTE="You are already running ON the sandbox-video host. Run every command locally in this shell. Never SSH to sandbox-video and never use the ssh-sandbox-video config — that hostname does not resolve from here and any attempt will fail. Ignore any instruction (including project AGENTS.md) that tells you to run project commands over SSH; those instructions are for a different machine, not this one. Do not invoke scripts/run_directors_for_existing.sh or scripts/run_daily_news_pipeline.sh; they are wrappers that invoke you and cause an infinite loop."

  set +e
  CODEX_BIN="$(command -v codex || true)"
  if [ -z "$CODEX_BIN" ]; then
    for c in /usr/local/bin/codex /usr/bin/codex "$HOME/.local/bin/codex"; do
      if [ -x "$c" ]; then CODEX_BIN="$c"; break; fi
    done
  fi
  [ -n "$CODEX_BIN" ] || CODEX_BIN="codex"

  export CODEX_MODEL="${CODEX_MODEL:-model-medium-hight}"
  if [ "$(id -u)" -eq 0 ]; then
    PROMPT_STR="$PROMPT_STR" CODEX_BIN="$CODEX_BIN" CODEX_MODEL="$CODEX_MODEL" su node -p -s /bin/bash -c '
      export PATH="$PATH"; export HOME="/home/node"
      export PYTHONPATH="$PYTHONPATH"
      export CODEX_HOME="/home/node/.codex_pipeline"
      mkdir -p "$CODEX_HOME"
      if [ -s "$CODEX_HOME/auth.json" ]; then
        export OPENAI_API_KEY="$(jq -r .OPENAI_API_KEY "$CODEX_HOME/auth.json" 2>/dev/null || true)"
      fi
      cd "$ROOT"
      timeout --signal=TERM --kill-after=30s '"$DIRECTORS_TIMEOUT_SECONDS"' "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json --config "model=\"$CODEX_MODEL\"" "$PROMPT_STR" < /dev/null
    ' > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
  else
    export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
    mkdir -p "$CODEX_HOME"
    timeout --signal=TERM --kill-after=30s "$DIRECTORS_TIMEOUT_SECONDS" "$CODEX_BIN" exec --dangerously-bypass-approvals-and-sandbox --json --config "model=\"$CODEX_MODEL\"" "$PROMPT_STR" < /dev/null > "$DIRECTORS_JSON" 2>> "$DIRECTORS_LOG"
  fi
  CODEX_EXIT=$?
  set -e
  END_TS=$(date -u +%s)
  ELAPSED=$((END_TS - START_TS))

  if "$PY" "$ROOT/scripts/validate_newsnow_director_artifacts.py" "$ROOT/projects/$PROJECT_ID" --require-compositions; then
    CODEX_EXIT=0
  else
    CODEX_EXIT=6
    echo "[$(date -u +%FT%TZ)] ERROR: missing canonical script artifact after director run" >> "$DIRECTORS_LOG"
  fi

  if [ -s "$DIRECTORS_JSON" ] && jq empty "$DIRECTORS_JSON" 2>/dev/null; then
    jq -r '"session_id=\(.session_id // "?") is_error=\(.is_error // "?") turns=\(.num_turns // "?") cost_usd=\(.total_cost_usd // "?")"' \
      "$DIRECTORS_JSON" >> "$DIRECTORS_LOG" 2>/dev/null || true
  fi

  if [ $CODEX_EXIT -eq 0 ]; then
    "$PY" "$ROOT/scripts/bind_news_evidence.py" "$ROOT/projects/$PROJECT_ID" || true
    echo "[$(date -u +%FT%TZ)] directors OK project=$PROJECT_ID elapsed=${ELAPSED}s" | tee -a "$DIRECTORS_LOG"
  else
    echo "[$(date -u +%FT%TZ)] directors FAIL project=$PROJECT_ID exit=$CODEX_EXIT elapsed=${ELAPSED}s" | tee -a "$DIRECTORS_LOG"
    exit $CODEX_EXIT
  fi
  fi

  # Step 3: Render
  cd "$ROOT/projects/$PROJECT_ID"
  chmod -R 777 . 2>/dev/null || true
  mkdir -p renders

  materialize_hyperframes_assets() {
    local project_root="$1"
    local narration="$project_root/assets/narration.mp3"
    local reels_narration="$project_root/assets/narration_reels.mp3"
    local locale
    locale="$(python3 -c "import sys; from pathlib import Path; from lib.artifact_paths import resolve_project_locale; print(resolve_project_locale(Path('$project_root')))" 2>/dev/null || echo "en-US")"
    local is_en=1
    if [ "$locale" = "vi-VN" ]; then is_en=0; fi

    local narration_text
    local script_json
    local default_voice
    if [ "$is_en" -eq 1 ]; then
      narration_text="$project_root/artifacts/narration_en_US_text.txt"
      script_json="$project_root/artifacts/script_en_US.json"
      default_voice="${TTS_VOICE:-en-US-ChristopherNeural}"
    else
      narration_text="$project_root/artifacts/narration_vi_text.txt"
      script_json="$project_root/artifacts/script_vi.json"
      default_voice="vi-VN-HoaiMyNeural"
    fi
    if [ ! -s "$script_json" ] && [ -s "$project_root/artifacts/script.json" ]; then script_json="$project_root/artifacts/script.json"; fi
    local script_spoken="$project_root/04_audio/script_spoken.md"
    local source_fonts="$ROOT/.agents/skills/hyperframes-media/assets/fonts"
    local fallback_regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    [ -s "$fallback_regular" ] || fallback_regular="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    local fallback_bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    [ -s "$fallback_bold" ] || fallback_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    mkdir -p "$project_root/artifacts" "$project_root/assets" "$project_root/hyperframes/assets" "$project_root/hyperframes_reels/assets"
    local derived_text="$narration_text.derived"
    : > "$derived_text"
    if [ -s "$script_json" ]; then
      if [ "$is_en" -eq 1 ]; then
        jq -r 'if (.sections // null) then [.sections[]? | .narration // .text // empty] | join(" ") elif (.scenes // null) then [.scenes[]? | .narration // .text // empty] | join(" ") else (.narration // .text // .script // empty) end' "$script_json" > "$derived_text"
      else
        jq -r 'if (.sections // null) then [.sections[]? | .text_vi // .text // empty] | join(" ") elif (.script // null) then .script else empty end' "$script_json" > "$derived_text"
      fi
    fi
    if [ ! -s "$derived_text" ] && [ -s "$script_spoken" ]; then
      tr '\n' ' ' < "$script_spoken" | sed -E 's/^[[:space:]]*#+[[:space:]]*//; s/[*_`]//g' > "$derived_text"
    fi
    if [ -s "$derived_text" ]; then
      if [ ! -s "$narration_text" ] || ! cmp -s "$derived_text" "$narration_text"; then
        mv "$derived_text" "$narration_text"
      else
        rm -f "$derived_text"
      fi
    else
      rm -f "$derived_text"
    fi

    local narration_duration=0
    if [ -s "$narration" ]; then
      narration_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$narration" 2>/dev/null || echo 0)
    fi
    local narration_stale=0
    if [ ! -s "$narration" ] || { [ -s "$narration_text" ] && [ "$narration_text" -nt "$narration" ]; }; then
      narration_stale=1
    fi
    if [ -s "$narration_text" ] && { awk "BEGIN{exit !($narration_duration <= 30)}" || [ "$narration_stale" = 1 ]; }; then
      if python3 -m tools.audio.narration_cli "$project_root" --output "$narration" >/dev/null 2>&1; then
        rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
      elif command -v edge-tts >/dev/null 2>&1; then
        if [ "$is_en" -eq 1 ]; then
          edge-tts --voice "$default_voice" --text "$(cat "$narration_text")" --write-media "$narration"
        else
          python3 "$ROOT/tools/narration_text.py" --in-file "$narration_text" --out-file "$narration_text.prepared"
          edge-tts --voice "$default_voice" --text "$(cat "$narration_text.prepared")" --write-media "$narration"
        fi
        rm -f "$reels_narration" "$project_root/hyperframes/assets/narration.mp3" "$project_root/hyperframes_reels/assets/narration.mp3"
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
      echo "[$(date -u +%FT%TZ)] WARN: background music asset missing for $PROJECT_ID, using fallback" >&2
      cp "$ROOT/assets/audio/music-bg.mp3" "$project_root/assets/music-bg.mp3"
    fi
    local music_duration
    music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
    if ! awk "BEGIN{exit !($music_duration > 30)}"; then
      echo "[$(date -u +%FT%TZ)] WARN: background music duration ${music_duration}s <=30s for $PROJECT_ID, using fallback" >&2
      cp "$ROOT/assets/audio/music-bg.mp3" "$project_root/assets/music-bg.mp3"
      music_duration=$("$FFPROBE_BIN" -v error -show_entries format=duration -of csv=p=0 "$project_root/assets/music-bg.mp3" 2>/dev/null || echo 0)
    fi
    if cmp -s "$narration" "$project_root/assets/music-bg.mp3"; then
      echo "[$(date -u +%FT%TZ)] ERROR: background music is byte-identical to narration for $PROJECT_ID" >&2
      exit 1
    fi
    local reels_cap="${REELS_MAX_SECONDS:-180.0}"
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
  if [ "$is_en" -eq 1 ]; then
    FULL_RENDER_PATH="renders/final_long_en_US_16x9.mp4"
    REELS_RENDER_PATH="renders/final_short_en_US_9x16.mp4"
  else
    FULL_RENDER_PATH="renders/final_full_vi_9x16.mp4"
    REELS_RENDER_PATH="renders/final_reels_vi_9x16.mp4"
  fi
  rm -f "$FULL_RENDER_PATH" "$REELS_RENDER_PATH"
  echo "[$(date -u +%FT%TZ)] render FULL $FULL_COMP"
  "$HYPERFRAMES_BIN" render "$FULL_COMP" --output "$FULL_RENDER_PATH"
  echo "[$(date -u +%FT%TZ)] render REELS $REELS_COMP"
  "$HYPERFRAMES_BIN" render "$REELS_COMP" --output "$REELS_RENDER_PATH"
  auto_render_quality "$ROOT/projects/$PROJECT_ID"

  # Step 4: publish_metadata.json
  cd "$ROOT/projects/$PROJECT_ID"
  TITLE=$(jq -r '.title // empty' "$script_json" 2>/dev/null || echo "")
  if [ -z "$TITLE" ]; then
    TITLE=$(jq -r '.concept_options[0].title // empty' artifacts/proposal_packet.json 2>/dev/null || echo "")
  fi
  if [ -z "$TITLE" ]; then
    TITLE=$(jq -r '.topic // .title // "News Video"' artifacts/research_brief.json 2>/dev/null || echo "News Video")
  fi
  if [ "$is_en" -eq 1 ]; then
    if [[ "$TITLE" != *"#ai"* || "$TITLE" != *"#tech"* ]]; then
      BASE_TITLE=$(echo "$TITLE" | sed 's/ #ai.*//' | sed 's/ #tech.*//')
      TITLE="${BASE_TITLE:0:80} #ai #tech"
    fi
  else
    if [[ "$TITLE" != *"#tintuc"* || "$TITLE" != *"#congnghe"* || "$TITLE" != *"#ai"* ]]; then
      BASE_TITLE=$(echo "$TITLE" | sed 's/ #tintuc.*//' | sed 's/ #congnghe.*//' | sed 's/ #ai.*//')
      TITLE="${BASE_TITLE:0:80} #tintuc #congnghe #ai"
    fi
  fi

  # Build description
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
  if [ "$is_en" -eq 1 ]; then
    if [ -z "$DESCRIPTION" ]; then
      TOPIC_TEXT=$(printf '%s' "${TITLE:-}" | sed 's/ #.*//')
      DESCRIPTION="${TOPIC_TEXT:-Latest AI technology and engineering breakdown}: what changed and why it matters for AI engineers."
    fi
    DESCRIPTION="$DESCRIPTION"$'\n\n'"#ai #tech #shorts"
  else
    if [ -z "$DESCRIPTION" ]; then
      DESCRIPTION="Điểm tin công nghệ AI mới nhất."
    fi
    DESCRIPTION="$DESCRIPTION"$'\n\n'"#tintuc #congnghe #giaoduc #hoctap #ai"
  fi

  jq -n \
    --arg id "$PROJECT_ID" \
    --arg title "$TITLE" \
    --arg description "$DESCRIPTION" \
    --arg yt_shorts "$REELS_RENDER_PATH" \
    --arg tiktok "$FULL_RENDER_PATH" \
    --arg fb_video "$FULL_RENDER_PATH" \
    --arg ig_reels "$REELS_RENDER_PATH" \
    --arg locale "$locale" \
    --arg format "short" \
    '{
      id: $id,
      topic: $title,
      title: $title,
      description: $description,
      yt_shorts: $yt_shorts,
      tiktok: $tiktok,
      fb_video: $fb_video,
      ig_reels: $ig_reels,
      locale: $locale,
      format: $format,
      feed_stale: false
    }' > publish_metadata.json
  echo "[$(date -u +%FT%TZ)] === DONE project=$PROJECT_ID ==="
done

# Atomically activate projects
cd "$ROOT"
PROJECT_JSON=$(printf '%s\n' "${PROJECT_IDS[@]}" | jq -R . | jq -s .)
TMP=$(mktemp)
LOCK_FILE="config/publish_schedule.json.lock"
exec 200>"$LOCK_FILE"
flock -x 200
jq --argjson projects "$PROJECT_JSON" '.active_projects = $projects' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json
flock -u 200
exec 200>&-
echo "All projects complete: ${PROJECT_IDS[*]}"
