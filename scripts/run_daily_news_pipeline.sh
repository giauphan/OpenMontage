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

# Step 0: Fetch fresh feed with stale fallback (P3)
FEED_STALE=0
NEWSNOW_URL="${NEWSNOW_API_URL:-}"
if [ -n "$NEWSNOW_URL" ]; then
  echo "[$(date -u +%FT%TZ)] Fetching fresh NewsNow feed..."
  if curl -sS -f --connect-timeout 10 --max-time 30 "$NEWSNOW_URL" -o "data/newsnow_feed.json.tmp"; then
    if jq empty "data/newsnow_feed.json.tmp" 2>/dev/null; then
      mv "data/newsnow_feed.json.tmp" "data/newsnow_feed.json"
      echo "[$(date -u +%FT%TZ)] Fresh feed saved to data/newsnow_feed.json"
    else
      echo "[$(date -u +%FT%TZ)] WARN: Received invalid JSON from NewsNow API. Using stale fallback."
      rm -f "data/newsnow_feed.json.tmp"
      FEED_STALE=1
    fi
  else
    echo "[$(date -u +%FT%TZ)] WARN: Failed to fetch NewsNow API feed. Using stale fallback."
    rm -f "data/newsnow_feed.json.tmp"
    FEED_STALE=1
  fi
else
  if [ -f "data/newsnow_feed.json" ]; then
    echo "[$(date -u +%FT%TZ)] NEWSNOW_API_URL not set; using existing data/newsnow_feed.json"
    FEED_STALE=1
  else
    echo "[$(date -u +%FT%TZ)] ERROR: No news feed available at data/newsnow_feed.json and NEWSNOW_API_URL not set."
    exit 1
  fi
fi

# Step 1: Run NewsNow pipeline to select topic and generate research brief (P1 fix: remove invalid --output arg)
"$PY" tools/news/news_pipeline_cli.py produce --input "data/newsnow_feed.json"

# Step 2: Extract latest selected project ID from checkpoint (P1)
PROJECT_ID=$(
  "$PY" -c "
import json
from pathlib import Path
checkpoints = list(Path('projects').rglob('checkpoint*.json'))
if not checkpoints:
    raise RuntimeError('No checkpoint.json found in projects/')
latest = max(checkpoints, key=lambda p: p.stat().st_mtime)
checkpoint = json.loads(latest.read_text())
print(checkpoint['project_id'])
  "
)

if [ -n "$PROJECT_ID" ] && [ -d "projects/$PROJECT_ID" ]; then
  chmod -R 777 "projects/$PROJECT_ID" 2>/dev/null || true
fi

echo "[$(date -u +%FT%TZ)] PROJECT_ID=$PROJECT_ID"

# Step 2.5: Run Directors pipeline via Claude CLI (unattended, logged) (P2)
DIRECTORS_LOG="$ROOT/logs/directors_${PROJECT_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"
START_TS=$(date -u +%s)

echo "[$(date -u +%FT%TZ)] directors START project=$PROJECT_ID" >> "$DIRECTORS_LOG"

DIRECTORS_JSON="$ROOT/logs/directors_${PROJECT_ID}_result.json"

set +e
PROMPT_STR="Run OpenMontage directors pipeline for projects/$PROJECT_ID. Read projects/$PROJECT_ID/artifacts/research_brief.json, then execute Proposal -> Script -> Scene -> Asset -> Compose directors in sequence. Generate both hyperframes/index.html (120s full) and hyperframes_reels/index.html (60s Reels cutdown) under projects/$PROJECT_ID/. Do not ask for confirmation between stages."

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
mkdir -p renders

FULL_COMP=""
if [ -f "hyperframes/index.html" ]; then
  FULL_COMP="hyperframes/index.html"
elif [ -f "Hyperframes/index.html" ]; then
  FULL_COMP="Hyperframes/index.html"
fi

REELS_COMP=""
if [ -f "hyperframes_reels/index.html" ]; then
  REELS_COMP="hyperframes_reels/index.html"
elif [ -f "Hyperframes_reels/index.html" ]; then
  REELS_COMP="Hyperframes_reels/index.html"
fi

if [ -n "$FULL_COMP" ] && [ ! -f "renders/final_full_vi_9x16.mp4" ]; then
  hyperframes render --composition "$FULL_COMP" --output renders/final_full_vi_9x16.mp4
fi
if [ -n "$REELS_COMP" ] && [ ! -f "renders/final_reels_vi_9x16.mp4" ]; then
  hyperframes render --composition "$REELS_COMP" --output renders/final_reels_vi_9x16.mp4
fi

# Sanity check rendered outputs
if [ ! -s "renders/final_full_vi_9x16.mp4" ] && [ ! -s "renders/final_reels_vi_9x16.mp4" ]; then
  echo "[$(date -u +%FT%TZ)] WARN: Neither renders/final_full_vi_9x16.mp4 nor renders/final_reels_vi_9x16.mp4 was generated/non-empty!"
fi
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

cat > "publish_metadata.json" <<EOF
{
  "id": "$PROJECT_ID",
  "title": "${TITLE:-News Video}",
  "description": "${SUMMARY:-AI generated news breakdown}",
  "yt_shorts": "renders/final_full_vi_9x16.mp4",
  "fb_reels": "renders/final_full_vi_9x16.mp4",
  "ig_reels": "renders/final_reels_vi_9x16.mp4",
  "feed_stale": $((FEED_STALE))
}
EOF

# Step 5: Update publish_schedule.json with new active project
cd "$ROOT"
TMP=$(mktemp)
jq --arg proj "$PROJECT_ID" '.active_projects |= [$proj]' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json

# Step 6: Run copyright preflight (if files exist)
if [ -f "projects/$PROJECT_ID/renders/final_full_vi_9x16.mp4" ]; then
  "$PY" scripts/check_copyright.py "projects/$PROJECT_ID/renders/final_full_vi_9x16.mp4" || true
fi
if [ -f "projects/$PROJECT_ID/renders/final_reels_vi_9x16.mp4" ]; then
  "$PY" scripts/check_copyright.py "projects/$PROJECT_ID/renders/final_reels_vi_9x16.mp4" || true
fi

echo "Daily pipeline completed: $PROJECT_ID (Feed stale: $FEED_STALE)"
