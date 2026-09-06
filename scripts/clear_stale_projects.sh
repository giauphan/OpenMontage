#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Default: only remove if older than 2 hours to avoid race with concurrent runs,
# or all unscheduled if --all passed.
MIN_AGE_MINUTES=120
if [ "${1:-}" = "--all" ]; then
    MIN_AGE_MINUTES=0
fi
CONFIG="$ROOT/config/publish_schedule.json"

if [ ! -f "$CONFIG" ]; then
    echo "No publish schedule found. Exiting."
    exit 0
fi

# Build a list of active project IDs
ACTIVE_IDS=$(jq -r '.active_projects[]? | (.project_id // .)' "$CONFIG" 2>/dev/null || echo "")

# Clean up projects and projects_news dirs
for DIR in "$ROOT"/projects/cand_* "$ROOT"/projects_news/cand_*; do
    [ -d "$DIR" ] || continue
    PID=$(basename "$DIR")
    # Check if this PID is active
    if echo "$ACTIVE_IDS" | grep -qx "$PID"; then
        continue
    fi
    # Delete if older than minimum age
    if [ -z "$(find "$DIR" -maxdepth 0 -mmin -${MIN_AGE_MINUTES})" ]; then
        echo "Removing stale orphaned project: $PID"
        rm -rf "$DIR"
    fi
done
