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
export PYTHONPATH="$ROOT"
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
  mkdir -p renders

  FULL_COMP=""
  if [ -d "hyperframes" ]; then FULL_COMP="hyperframes"
  elif [ -d "Hyperframes" ]; then FULL_COMP="Hyperframes"
  fi
  REELS_COMP=""
  if [ -d "hyperframes_reels" ]; then REELS_COMP="hyperframes_reels"
  elif [ -d "Hyperframes_reels" ]; then REELS_COMP="Hyperframes_reels"
  fi

  if [ -n "$FULL_COMP" ] && [ ! -f "renders/final_full_vi_9x16.mp4" ]; then
    echo "[$(date -u +%FT%TZ)] render FULL $FULL_COMP"
    hyperframes render "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
  fi
  if [ -n "$REELS_COMP" ] && [ ! -f "renders/final_reels_vi_9x16.mp4" ]; then
    echo "[$(date -u +%FT%TZ)] render REELS $REELS_COMP"
    hyperframes render "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
  fi

  require_video() {
    local path="$1"
    if [ ! -s "$path" ]; then echo "[$(date -u +%FT%TZ)] ERROR: $path missing or empty"; exit 1; fi
    local dur; dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$path" 2>/dev/null || echo 0)
    if ! awk "BEGIN{exit !($dur > 30)}"; then echo "[$(date -u +%FT%TZ)] ERROR: $path duration ${dur}s <=30s"; exit 1; fi
    if [ -z "$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$path" 2>/dev/null)" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: $path has no audio"; exit 1
    fi
    echo "[$(date -u +%FT%TZ)] render OK $path dur=${dur}s"
  }
  require_video "renders/final_full_vi_9x16.mp4"
  require_video "renders/final_reels_vi_9x16.mp4"

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
