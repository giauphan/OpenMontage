#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Define age threshold: 2 days
MIN_AGE_MINUTES=$(( 48 * 60 ))
CONFIG="$ROOT/config/publish_schedule.json"

if [ ! -f "$CONFIG" ]; then
    echo "No publish schedule found. Exiting."
    exit 0
fi

# Build a list of active project IDs
ACTIVE_IDS=$(jq -r '.active_projects[] | (.project_id // .)' "$CONFIG" 2>/dev/null || echo "")

for PDIR in "$ROOT"/projects/cand_*; do
    [ -d "$PDIR" ] || continue
    PID=$(basename "$PDIR")
    # Check if this PID is active
    if echo "$ACTIVE_IDS" | grep -qx "$PID"; then
        continue
    fi
    # Delete if older than minimum age
    if [ -z "$(find "$PDIR" -maxdepth 0 -mmin -${MIN_AGE_MINUTES})" ]; then
        echo "Removing stale orphaned project: $PID"
        rm -rf "$PDIR"
    fi
done
