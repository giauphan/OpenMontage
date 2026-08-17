#!/usr/bin/env bash
# Daily AI news video generation pipeline.
# Selects trending topic, generates Vietnamese video (120s + 60s Reels), updates publish_schedule.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

export PYTHONPATH="$ROOT"

if [ -n "${OPENMONTAGE_PYTHON:-}" ]; then
  PY="$OPENMONTAGE_PYTHON"
elif [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="$(command -v python3)"
fi

# Step 1: Run NewsNow pipeline to select topic and generate research brief
"$PY" tools/news/news_pipeline_cli.py produce --input "data/newsnow_feed.json" --output "data/ranked_candidates.json"

# Step 2: Extract selected project ID from checkpoint
PROJECT_ID=$(
  "$PY" -c "
import json
from pathlib import Path
checkpoint = json.loads(Path('projects').rglob('checkpoint.json').__next__().read_text())
print(checkpoint['project_id'])
  "
)

# Step 3: Render video (120s + 60s Reels)
cd "projects/$PROJECT_ID"
if [ ! -f "renders/final_full_vi_9x16.mp4" ]; then
  hyperframes render --composition hyperframes/index.html --output renders/final_full_vi_9x16.mp4
fi
if [ ! -f "renders/final_reels_vi_9x16.mp4" ]; then
  hyperframes render --composition hyperframes_reels/index.html --output renders/final_reels_vi_9x16.mp4
fi

# Step 4: Create publish_metadata.json
cat > "publish_metadata.json" <<EOF
{
  "id": "$PROJECT_ID",
  "title": "$(jq -r '.artifacts.research_brief.topic' artifacts/research_brief.json)",
  "description": "$(jq -r '.artifacts.research_brief.summary' artifacts/research_brief.json)",
  "yt_shorts": "renders/final_full_vi_9x16.mp4",
  "fb_reels": "renders/final_full_vi_9x16.mp4",
  "ig_reels": "renders/final_reels_vi_9x16.mp4"
}
EOF

# Step 5: Update publish_schedule.json with new active project
cd "$ROOT"
TMP=$(mktemp)
jq --arg proj "$PROJECT_ID" '.active_projects |= [$proj]' config/publish_schedule.json > "$TMP"
mv "$TMP" config/publish_schedule.json

# Step 6: Run copyright preflight
"$PY" scripts/check_copyright.py "projects/$PROJECT_ID/renders/final_full_vi_9x16.mp4"
"$PY" scripts/check_copyright.py "projects/$PROJECT_ID/renders/final_reels_vi_9x16.mp4"

echo "Daily pipeline completed: $PROJECT_ID"