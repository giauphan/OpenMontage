#!/usr/bin/env bash
set -e

# Initialize isolated Codex profiles if source directory exists and has credentials
INIT_SCRIPT="${OPENMONTAGE_ROOT:-/app}/scripts/init_codex_profile.sh"
[ -f "$INIT_SCRIPT" ] || INIT_SCRIPT="/app/scripts/init_codex_profile.sh"

SOURCE_DIR="${CODEX_SOURCE_DIR:-/etc/codex_source}"

if [ -f "$INIT_SCRIPT" ] && [ -d "$SOURCE_DIR" ] && [ -f "$SOURCE_DIR/auth.json" ]; then
  bash "$INIT_SCRIPT" "$SOURCE_DIR" /root/.codex_pipeline root 2>/dev/null || true
  bash "$INIT_SCRIPT" "$SOURCE_DIR" /home/node/.codex_pipeline node 2>/dev/null || true
fi

exec "$@"
