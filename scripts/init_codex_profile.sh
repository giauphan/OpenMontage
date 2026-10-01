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

if [ ! -f "$SOURCE_DIR/config.toml" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: source directory missing config.toml" >&2
  exit 1
fi

# Do not overwrite if it already exists and holds valid auth, unless explicitly refreshed.
if [ -s "$TARGET_DIR/auth.json" ] && [ "${REFRESH_CODEX_PROFILE:-0}" != "1" ]; then
  # Still validate the existing target directory
  if ! jq -e '.OPENAI_API_KEY | type == "string" and length > 0' "$TARGET_DIR/auth.json" >/dev/null 2>&1; then
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Existing target auth.json lacks valid OPENAI_API_KEY." >&2
    exit 1
  fi
  if [ ! -s "$TARGET_DIR/config.toml" ] || ! grep -q -E "^[[:space:]]*model_provider[[:space:]]*=" "$TARGET_DIR/config.toml"; then
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Existing target config.toml lacks valid model_provider." >&2
    exit 1
  fi
  exit 0
fi

# Create a staging directory for atomic replacement
STAGING_DIR="${TARGET_DIR}_staging_$$"
BACKUP_DIR=""
mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"

cleanup() {
  local exit_code=$?
  # If TARGET_DIR was moved to BACKUP_DIR, but STAGING failed to become TARGET_DIR, restore BACKUP_DIR
  if [ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ] && [ ! -d "$TARGET_DIR" ]; then
    echo "[$(date -u +%FT%TZ)] RESTORE: Restoring backup profile to $TARGET_DIR after activation failure" >&2
    mv "$BACKUP_DIR" "$TARGET_DIR" || true
  fi
  # Clean up staging directory
  if [ -n "${STAGING_DIR:-}" ] && [ -d "$STAGING_DIR" ]; then
    rm -rf "$STAGING_DIR" || true
  fi
  # Clean up backup directory if target is present
  if [ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ] && [ -d "$TARGET_DIR" ]; then
    rm -rf "$BACKUP_DIR" || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

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

if ! jq -e '.OPENAI_API_KEY | type == "string" and length > 0' "$STAGING_DIR/auth.json" >/dev/null 2>&1; then
  echo "[$(date -u +%FT%TZ)] ERROR: auth.json missing OPENAI_API_KEY payload" >&2
  exit 1
fi

if [ ! -f "$STAGING_DIR/config.toml" ] || ! grep -q -E "^[[:space:]]*model_provider[[:space:]]*=" "$STAGING_DIR/config.toml"; then
  echo "[$(date -u +%FT%TZ)] ERROR: config.toml missing model_provider configuration" >&2
  exit 1
fi

# Atomic replacement: swap the staging directory into the target location
# Key rotation procedure:
# 1. Update source files in /etc/codex_source (or CODEX_SOURCE_DIR).
# 2. Run init_codex_profile.sh with REFRESH_CODEX_PROFILE=1 to force replacement.
# 3. Restart containers with: docker compose restart scheduler worker
#    (Note: `docker compose up -d` will NOT pick up mounted file updates if container spec is unchanged).
LOCK_FILE="${TARGET_DIR}.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -u +%FT%TZ)] ERROR: Another profile initialization is running for $TARGET_DIR" >&2
  exit 1
fi

if [ -d "$TARGET_DIR" ]; then
  BACKUP_DIR="${TARGET_DIR}_bak_$$"
  mv "$TARGET_DIR" "$BACKUP_DIR"
  if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
    echo "[$(date -u +%FT%TZ)] ERROR: Failed to activate staging directory to $TARGET_DIR" >&2
    exit 1
  fi
  rm -rf "$BACKUP_DIR"
  BACKUP_DIR=""
else
  if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
    echo "[$(date -u +%FT%TZ)] ERROR: Failed to activate staging directory to $TARGET_DIR" >&2
    exit 1
  fi
fi

trap - EXIT INT TERM

echo "[$(date -u +%FT%TZ)] SUCCESS: Profile initialized at $TARGET_DIR for user $TARGET_USER"
