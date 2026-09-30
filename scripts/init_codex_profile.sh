#!/usr/bin/env bash
# OpenMontage - Initialize isolated Codex pipeline runtime profile
# Copies credentials and configuration from read-only host mount source into a private,
# isolated runtime directory without exposing secrets in logs or git.
set -euo pipefail

SOURCE_DIR="${1:-${CODEX_SOURCE_DIR:-/etc/codex_source}}"
TARGET_DIR="${2:-${CODEX_HOME:-/root/.codex_pipeline}}"

mkdir -p "$TARGET_DIR"
chmod 700 "$TARGET_DIR"

if [ -d "$SOURCE_DIR" ] && [ -f "$SOURCE_DIR/auth.json" ]; then
  if [ ! -f "$TARGET_DIR/auth.json" ] || [ "${REFRESH_CODEX_PROFILE:-0}" = "1" ]; then
    cp -f "$SOURCE_DIR/auth.json" "$TARGET_DIR/auth.json" 2>/dev/null || true
    if [ -f "$SOURCE_DIR/config.toml" ]; then
      cp -f "$SOURCE_DIR/config.toml" "$TARGET_DIR/config.toml" 2>/dev/null || true
    fi
    if [ -f "$SOURCE_DIR/version.json" ]; then
      cp -f "$SOURCE_DIR/version.json" "$TARGET_DIR/version.json" 2>/dev/null || true
    fi
    if [ -f "$SOURCE_DIR/models_cache.json" ]; then
      cp -f "$SOURCE_DIR/models_cache.json" "$TARGET_DIR/models_cache.json" 2>/dev/null || true
    fi
    chmod 600 "$TARGET_DIR"/* 2>/dev/null || true
  fi
fi

# Validation: ensure target contains non-empty auth.json and config.toml
if [ ! -s "$TARGET_DIR/auth.json" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: CODEX_HOME auth.json is missing or empty at $TARGET_DIR" >&2
  exit 1
fi

if [ ! -s "$TARGET_DIR/config.toml" ]; then
  echo "[$(date -u +%FT%TZ)] ERROR: CODEX_HOME config.toml is missing or empty at $TARGET_DIR" >&2
  exit 1
fi

TEST_FILE="$TARGET_DIR/.write_test_$$"
if ! touch "$TEST_FILE" 2>/dev/null; then
  echo "[$(date -u +%FT%TZ)] ERROR: CODEX_HOME is not writable at $TARGET_DIR" >&2
  exit 1
fi
rm -f "$TEST_FILE"
