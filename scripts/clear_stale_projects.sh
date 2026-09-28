#!/bin/bash
set -euo pipefail
ROOT="${OPENMONTAGE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

MIN_AGE_MINUTES=120
DRY_RUN=0
ALL=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=1
            ;;
        --all)
            MIN_AGE_MINUTES=0
            ALL=1
            ;;
        --min-age=*)
            MIN_AGE_MINUTES="${arg#*=}"
            ;;
    esac
done

CONFIG="$ROOT/config/publish_schedule.json"

if [ ! -f "$CONFIG" ]; then
    echo "No publish schedule found. Exiting."
    exit 0
fi

# Build lists of active and retry-protected project IDs
ACTIVE_IDS=$(jq -r '.active_projects[]? | (.project_id // .)' "$CONFIG" 2>/dev/null || echo "")
RETRY_IDS=$(jq -r '.active_projects[]? | select((.retry_count // 0) > 0 or .status == "auth_blocked" or .status == "failed" or .status == "validation_rejected" or .fatal_error == true) | (.project_id // .)' "$CONFIG" 2>/dev/null || echo "")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$ROOT:$REPO_ROOT:${PYTHONPATH:-}"

PYTHON_BIN=""
for candidate in "${PYTHON_BIN:-}" python3 "$REPO_ROOT/.venv/bin/python3" /usr/bin/python3; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c "import scripts.check_cleanup_eligibility" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

# Inspect projects, projects_news, and projects/instagram dirs
for DIR in "$ROOT"/projects/cand_* "$ROOT"/projects_news/cand_* "$ROOT"/projects/instagram/cand_*; do
    [ -d "$DIR" ] || continue
    PID=$(basename "$DIR")

    # Exclude active projects
    if echo "$ACTIVE_IDS" | grep -qx "$PID"; then
        continue
    fi

    # Exclude retry-pending or protected projects
    if echo "$RETRY_IDS" | grep -qx "$PID"; then
        continue
    fi

    # Check minimum age unless --all (widens inventory only, does not authorize unverified deletion)
    if [ "$ALL" -eq 0 ] && [ -n "$(find "$DIR" -maxdepth 0 -mmin -${MIN_AGE_MINUTES} 2>/dev/null)" ]; then
        continue
    fi

    # Verify eligibility against the canonical contract: ALL required destinations must be verified published
    if ! "$PYTHON_BIN" -m scripts.check_cleanup_eligibility --pid "$PID" --dir "$DIR" >/dev/null 2>&1; then
        # Unverified or incomplete publication: NEVER delete regardless of age or --all
        continue
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[DRY-RUN] Would remove verified published stale project: $PID at $DIR (published=1)"
    else
        echo "Removing verified published stale project: $PID at $DIR"
        "$PYTHON_BIN" -c "
import sys
from scripts.publish_active_projects import deactivate_project
ok = deactivate_project('$PID', project_dir='$DIR')
sys.exit(0 if ok else 1)
" || echo "WARNING: deactivate_project failed for $PID at $DIR"
    fi
done
