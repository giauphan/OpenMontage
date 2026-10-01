#!/usr/bin/env bash
# OpenMontage - Initialize isolated Codex pipeline runtime profile
# Copies credentials and configuration from read-only host mount source into a private,
# isolated runtime directory. Replaces the destination files atomically without reader-visible gaps.
# Validates that JSON/TOML configurations are well-formed and contain required fields.
set -euo pipefail

validate_profile_dir() {
  local dir="$1"
  python3 -c '
import sys, json
from pathlib import Path

dir_path = Path(sys.argv[1])
auth_file = dir_path / "auth.json"
config_file = dir_path / "config.toml"

if not auth_file.is_file() or auth_file.stat().st_size == 0:
    sys.exit("Missing or empty auth.json")
try:
    auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
except Exception as e:
    sys.exit(f"Invalid JSON in auth.json: {e}")
if not isinstance(auth_data, dict):
    sys.exit("auth.json is not a JSON object")
api_key = auth_data.get("OPENAI_API_KEY")
if not api_key or not isinstance(api_key, str) or not api_key.strip():
    sys.exit("auth.json missing or invalid OPENAI_API_KEY")

if not config_file.is_file() or config_file.stat().st_size == 0:
    sys.exit("Missing or empty config.toml")

content = config_file.read_text(encoding="utf-8")

# 1. Try tomllib or tomli if available
try:
    import tomllib
    data = tomllib.loads(content)
    if not isinstance(data, dict):
        sys.exit("Parsed TOML is not a dictionary")
    if "model_provider" not in data:
        sys.exit("config.toml missing model_provider configuration")
    mp = data["model_provider"]
    if not isinstance(mp, str) or not mp.strip():
        sys.exit("config.toml missing model_provider configuration")
    sys.exit(0)
except ImportError:
    try:
        import tomli
        data = tomli.loads(content)
        if not isinstance(data, dict):
            sys.exit("Parsed TOML is not a dictionary")
        if "model_provider" not in data:
            sys.exit("config.toml missing model_provider configuration")
        mp = data["model_provider"]
        if not isinstance(mp, str) or not mp.strip():
            sys.exit("config.toml missing model_provider configuration")
        sys.exit(0)
    except ImportError:
        pass
    except Exception as e:
        sys.exit(f"Invalid TOML syntax: {e}")
except Exception as e:
    sys.exit(f"Invalid TOML syntax: {e}")

# 2. Strict fallback line-by-line parser if no tomli/tomllib
root_config = {}
seen_keys = set()
current_table = None

for line_idx, raw_line in enumerate(content.splitlines(), start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("["):
        if line.startswith("[["):
            if not line.endswith("]]") or len(line) <= 4:
                sys.exit(f"Line {line_idx}: malformed array-of-tables header")
            current_table = line[2:-2].strip()
        else:
            if not line.endswith("]") or len(line) <= 2:
                sys.exit(f"Line {line_idx}: malformed table header")
            current_table = line[1:-1].strip()
        continue
    if "=" not in line:
        sys.exit(f"Line {line_idx}: invalid TOML syntax, expected key = value")
    key_part, val_part = line.split("=", 1)
    key = key_part.strip()
    val = val_part.strip()
    if not key or not val:
        sys.exit(f"Line {line_idx}: missing key or value")

    if current_table is None:
        if key in seen_keys:
            sys.exit(f"Line {line_idx}: Duplicate key {key}")
        seen_keys.add(key)

    if val.startswith("\""):
        end_quote = val.find("\"", 1)
        if end_quote == -1:
            sys.exit(f"Line {line_idx}: unterminated double-quoted string")
        rem = val[end_quote+1:].strip()
        if rem and not rem.startswith("#"):
            sys.exit(f"Line {line_idx}: unexpected trailing characters")
        parsed_val = val[1:end_quote]
        val_type = "string"
    elif val.startswith("\x27"):
        end_quote = val.find("\x27", 1)
        if end_quote == -1:
            sys.exit(f"Line {line_idx}: unterminated single-quoted string")
        rem = val[end_quote+1:].strip()
        if rem and not rem.startswith("#"):
            sys.exit(f"Line {line_idx}: unexpected trailing characters")
        parsed_val = val[1:-1]
        val_type = "string"
    elif val.lower() in ("true", "false"):
        val_type = "boolean"
        parsed_val = val.lower() == "true"
    elif val.lstrip("-").isdigit():
        val_type = "integer"
        parsed_val = int(val)
    elif val.startswith("[") or val.startswith("{"):
        val_type = "complex"
        parsed_val = val
    else:
        val_no_c = val.split("#", 1)[0].strip()
        if not val_no_c:
            sys.exit(f"Line {line_idx}: missing value")
        # Identify standard unquoted TOML types: float or datetime
        import re
        if re.fullmatch(r"[+-]?(0|[1-9](_?[0-9])*)(\.[0-9](_?[0-9])*)?([eE][+-]?[0-9](_?[0-9])*)?", val_no_c) or val_no_c in ("inf", "+inf", "-inf", "nan", "+nan", "-nan"):
            val_type = "float"
            parsed_val = float(val_no_c)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?", val_no_c):
            val_type = "datetime"
            parsed_val = val_no_c
        else:
            sys.exit(f"Line {line_idx}: Invalid TOML syntax or value for key {key}: {val_no_c}")

    if current_table is None:
        root_config[key] = (parsed_val, val_type)

if "model_provider" not in root_config:
    sys.exit("config.toml missing model_provider configuration")
v, v_type = root_config["model_provider"]
if v_type != "string" or not isinstance(v, str) or not v.strip():
    sys.exit("config.toml missing model_provider configuration")
' "$dir"
}

SOURCE_DIR="${1:-${CODEX_SOURCE_DIR:-/etc/codex_source}}"
TARGET_DIR="${2:-${CODEX_HOME:-/root/.codex_pipeline}}"
TARGET_USER="${3:-$(id -u -n)}"

# R2: If source directory or required source files are missing, fail visibly unless target already holds valid runtime.
if [ ! -d "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/auth.json" ] || [ ! -f "$SOURCE_DIR/config.toml" ]; then
  if [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/auth.json" ] && [ -f "$TARGET_DIR/config.toml" ]; then
    if validate_err=$(validate_profile_dir "$TARGET_DIR" 2>&1); then
      echo "[$(date -u +%FT%TZ)] INIT INFO: Source directory $SOURCE_DIR missing/incomplete, but valid target profile exists at $TARGET_DIR. Reusing existing runtime."
      exit 0
    else
      echo "[$(date -u +%FT%TZ)] INIT ERROR: Source $SOURCE_DIR lacks auth.json/config.toml and existing target at $TARGET_DIR is invalid: $validate_err" >&2
      exit 1
    fi
  else
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Source $SOURCE_DIR lacks auth.json/config.toml and no valid target exists at $TARGET_DIR." >&2
    exit 1
  fi
fi

# Do not overwrite if target already exists, unless explicitly refreshed.
if [ -d "$TARGET_DIR" ] && ([ -e "$TARGET_DIR/auth.json" ] || [ -e "$TARGET_DIR/config.toml" ]) && [ "${REFRESH_CODEX_PROFILE:-0}" != "1" ]; then
  if ! validate_err=$(validate_profile_dir "$TARGET_DIR" 2>&1); then
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Existing target profile is invalid: $validate_err" >&2
    exit 1
  fi
  echo "[$(date -u +%FT%TZ)] INIT INFO: Existing target profile at $TARGET_DIR is valid and REFRESH_CODEX_PROFILE!=1. Skipping replacement."
  exit 0
fi

# Ensure target directory exists with secure permissions before staging
mkdir -p "$TARGET_DIR"
chmod 700 "$TARGET_DIR"
chown "$TARGET_USER" "$TARGET_DIR"

# R3: Concurrency protection via non-blocking flock
LOCK_FILE="${TARGET_DIR}.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -u +%FT%TZ)] ERROR: Another profile initialization is running for $TARGET_DIR" >&2
  exit 1
fi

# Stage files in a sibling staging directory on the same filesystem
STAGING_DIR="${TARGET_DIR}_staging_$$"
BACKUP_DIR="${TARGET_DIR}_bak_$$"
mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"
chown "$TARGET_USER" "$STAGING_DIR"

cleanup() {
  local exit_code=$?
  if [ -n "${STAGING_DIR:-}" ] && [ -d "$STAGING_DIR" ]; then
    rm -rf "$STAGING_DIR" || true
  fi

  if [ "$exit_code" -ne 0 ]; then
    # If target is missing but backup exists, restore it!
    if [ -d "${BACKUP_DIR:-}" ] && [ ! -d "$TARGET_DIR" ]; then
      echo "[$(date -u +%FT%TZ)] ROLLBACK: Restoring previous profile from backup..." >&2
      if ! mv "$BACKUP_DIR" "$TARGET_DIR"; then
        echo "[$(date -u +%FT%TZ)] CRITICAL: Failed to rollback profile from $BACKUP_DIR!" >&2
      fi
    elif [ -d "${BACKUP_DIR:-}" ]; then
      echo "[$(date -u +%FT%TZ)] ERROR: init failed. Backup directory is retained at $BACKUP_DIR for manual recovery." >&2
    fi
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

# Copy complete configuration snapshot into staging
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

# Apply correct ownership and permissions to staged files
chown -R "$TARGET_USER" "$STAGING_DIR"
chmod 600 "$STAGING_DIR"/*

# Validate staged profile before activation
if ! validate_err=$(validate_profile_dir "$STAGING_DIR" 2>&1); then
  echo "[$(date -u +%FT%TZ)] ERROR: $validate_err" >&2
  exit 1
fi

# R3: Profile-level consistency via directory swap
# Ensure readers never observe mixed versions by displacing the entire directory at once
if [ -d "$TARGET_DIR" ] && [ "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]; then
  if ! mv "$TARGET_DIR" "$BACKUP_DIR"; then
    echo "[$(date -u +%FT%TZ)] ERROR: Failed to move existing profile out of the way" >&2
    exit 1
  fi
  if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
    echo "[$(date -u +%FT%TZ)] ROLLBACK: Activation failed, restoring previous profile from backup..." >&2
    if ! mv "$BACKUP_DIR" "$TARGET_DIR"; then
      echo "[$(date -u +%FT%TZ)] CRITICAL: Failed to rollback profile from $BACKUP_DIR! Target is missing!" >&2
    fi
    exit 1
  fi
  rm -rf "$BACKUP_DIR"
else
  # First-time initialization. TARGET_DIR might exist as an empty dir from mkdir -p above.
  # rmdir it so mv places STAGING_DIR exactly at TARGET_DIR rather than nesting it.
  rmdir "$TARGET_DIR" 2>/dev/null || true
  if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
    echo "[$(date -u +%FT%TZ)] ERROR: Failed to move staging into target" >&2
    exit 1
  fi
fi

trap - EXIT INT TERM

echo "[$(date -u +%FT%TZ)] SUCCESS: Profile initialized at $TARGET_DIR for user $TARGET_USER"
