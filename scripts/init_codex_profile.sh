#!/usr/bin/env bash
# OpenMontage - Initialize isolated Codex pipeline runtime profile
# Copies credentials and configuration from read-only host mount source into a private,
# isolated runtime directory. Replaces the destination atomically as a unit.
# Validates that JSON/TOML configurations are well-formed and contain required fields.
set -euo pipefail

SOURCE_DIR="${1:-${CODEX_SOURCE_DIR:-/etc/codex_source}}"
TARGET_DIR="${2:-${CODEX_HOME:-/root/.codex_pipeline}}"
TARGET_USER="${3:-$(id -u -n)}"

if [ ! -d "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/auth.json" ]; then
  echo "[$(date -u +%FT%TZ)] INIT INFO: Source directory $SOURCE_DIR lacking auth.json. Skipping replacement."
  exit 0
fi

# Do not overwrite if it already exists and holds valid auth, unless explicitly refreshed.
if [ -s "$TARGET_DIR/auth.json" ] && [ "${REFRESH_CODEX_PROFILE:-0}" != "1" ]; then
  # Still validate the existing target directory
  if ! jq -e 'has("OPENAI_API_KEY")' "$TARGET_DIR/auth.json" >/dev/null 2>&1; then
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Existing target auth.json lacks OPENAI_API_KEY." >&2
    exit 1
  fi
  exit 0
fi

# Create a staging directory for atomic replacement
STAGING_DIR="${TARGET_DIR}_staging_$$"
mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"

trap 'rm -rf "$STAGING_DIR"' EXIT

# Copy complete configuration snapshot
cp -a "$SOURCE_DIR/auth.json" "$STAGING_DIR/auth.json"
if [ -f "$SOURCE_DIR/config.toml" ]; then
  cp -a "$SOURCE_DIR/config.toml" "$STAGING_DIR/config.toml"
fi
if [ -f "$SOURCE_DIR/version.json" ]; then
  cp -a "$SOURCE_DIR/version.json" "$STAGING_DIR/version.json"
fi
if [ -f "$SOURCE_DIR/models_cache.json" ]; then
  cp -a "$SOURCE_DIR/models_cache.json" "$STAGING_DIR/models_cache.json"
fi

# Apply correct ownership and permissions before making active
chown -R "$TARGET_USER" "$STAGING_DIR"
chmod 600 "$STAGING_DIR"/*

# Validate JSON/TOML structural integrity & presence of keys
if ! jq -e '.|type=="object"' "$STAGING_DIR/auth.json" >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] ERROR: auth.json from source is invalid JSON" >&2
  exit 1
fi

if ! jq -e 'has("OPENAI_API_KEY")' "$STAGING_DIR/auth.json" >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] ERROR: auth.json missing OPENAI_API_KEY payload" >&2
  exit 1
fi

if [ -f "$STAGING_DIR/config.toml" ]; then
  if ! grep -q "model_provider" "$STAGING_DIR/config.toml"; then
    echo "[$(date -u +%FT%TZ)] ERROR: config.toml missing model_provider configuration" >&2
    exit 1
  fi
fi

# Atomic replacement: swap the staging directory into the target location
if [ -d "$TARGET_DIR" ]; then
  BACKUP_DIR="${TARGET_DIR}_bak_$$"
  mv "$TARGET_DIR" "$BACKUP_DIR"
  mv "$STAGING_DIR" "$TARGET_DIR"
  rm -rf "$BACKUP_DIR"
else
  mv "$STAGING_DIR" "$TARGET_DIR"
fi

trap - EXIT

echo "[$(date -u +%FT%TZ)] SUCCESS: Profile initialized at $TARGET_DIR for user $TARGET_USER"
