#!/usr/bin/env bash
# OpenMontage - Initialize isolated Codex pipeline runtime profile.
#
# Copies credentials + configuration from a read-only host mount source into a
# private, isolated runtime directory and activates them in a way that is
# CONSISTENT FOR READERS.
#
# Reader-consistent activation model:
#   $TARGET_DIR is a SYMLINK to a versioned generation directory:
#       $TARGET_DIR -> $TARGET_DIR.store/gen_<id>/   (auth.json, config.toml, ...)
#   A refresh builds a fully-validated NEW generation, then swaps the symlink
#   pointer with a single atomic rename(2). Readers that resolve $TARGET_DIR
#   therefore observe EITHER the complete previous generation OR the complete
#   new generation - never a missing directory, and never a mix of two
#   generations. The live generation is never displaced during a refresh.
#
#   - On activation failure the symlink still points at the previous
#     (intact, retained) generation, so recovery data is never lost.
#   - On success, superseded generations older than (current + previous) are
#     pruned; the previous generation is retained as a rollback point.
#   - First-time initialization creates the symlink layout.
#   - A legacy real-directory target is migrated once to the symlink layout,
#     preserving its contents as a retained generation.
#
# Configuration validation:
#   auth.json must be a JSON object with a non-empty string OPENAI_API_KEY.
#   config.toml must be well-formed and contain a non-empty string
#   root-level model_provider. Parsing prefers tomllib (py3.11+) / tomli; when
#   neither is available a strict, fail-closed line validator is used that
#   rejects malformed values of every type (strings, booleans, integers,
#   floats, datetimes, single-line arrays, single-line inline tables) and any
#   duplicate keys / malformed syntax anywhere in the file.
set -euo pipefail

# --- Profile-directory validator (strict, fail-closed, no credential leak) ---
validate_profile_dir() {
  local dir="$1"
  python3 - "$dir" <<'PYCODE'
import sys, json, re
from pathlib import Path

# Standard-compliant TOML parser, preferred when present (handles multi-line
# arrays/tables that the fallback deliberately rejects as fail-closed).
def _try_authoritative_parse(content):
    try:
        import tomllib
        return tomllib.loads(content), "tomllib"
    except ImportError:
        pass
    try:
        import tomli
        return tomli.loads(content), "tomli"
    except ImportError:
        return None, None

# ---------------------------------------------------------------------------
# Strict single-line TOML fallback validator.
# Validates the whole document: table headers, key/value syntax, and every
# value type (string, boolean, integer, float, datetime, single-line array,
# single-line inline table). Rejects malformed syntax, duplicate keys,
# duplicate table headers, and any value it cannot fully validate (e.g.
# multi-line arrays) -> fail-closed.
# ---------------------------------------------------------------------------
INT_RE = re.compile(r"[+-]?(0x[0-9a-fA-F_]+|0o[0-7_]+|0b[0-1_]+|(0|[1-9](_?[0-9])*))")
FLOAT_RE = re.compile(r"([+-]?(0|[1-9](_?[0-9])*)(\.[0-9](_?[0-9])*)?([eE][+-]?[0-9](_?[0-9])*)?)|([+-]?(inf|nan))")
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?([zZ]|[+-]\d{2}:\d{2})?")
KEY_SEG_RE = re.compile(r"[A-Za-z0-9_-]+")


def _close_quote(s, q):
    i, n = 1, len(s)
    while i < n:
        ch = s[i]
        if q == '"' and ch == "\\":
            if i + 1 >= n:
                return None
            i += 2
            continue
        if ch == q:
            return i
        i += 1
    return None


def _validate_basic_string_inner(inner):
    # inner excludes the surrounding quotes; validate basic-string escapes.
    i, n = 0, len(inner)
    while i < n:
        ch = inner[i]
        if ch != "\\":
            i += 1
            continue
        if i + 1 >= n:
            return False
        esc = inner[i + 1]
        if esc in "btnfr\"\\":
            i += 2
            continue
        if esc == "u":
            if i + 6 > n or not all(c in "0123456789abcdefABCDEF" for c in inner[i + 2:i + 6]):
                return False
            i += 6
            continue
        if esc == "U":
            if i + 10 > n or not all(c in "0123456789abcdefABCDEF" for c in inner[i + 2:i + 10]):
                return False
            i += 10
            continue
        return False
    return True


def _rstrip_comment(v):
    in_s, q, i, n = False, None, 0, len(v)
    while i < n:
        ch = v[i]
        if in_s:
            if q == '"' and ch == "\\":
                i += 1
            elif ch == q:
                in_s = False
        else:
            if ch == '"' or ch == "'":
                in_s, q = True, ch
            elif ch == "#":
                return v[:i]
        i += 1
    return v


def _valid_key(k):
    if not k:
        return False
    if k[0] in "\"'":
        q = k[0]
        end = _close_quote(k, q)
        return end is not None and end == len(k) - 1
    parts = k.split(".")
    if any(p == "" for p in parts):
        return False
    return len(parts) >= 1 and all(KEY_SEG_RE.fullmatch(p) for p in parts)


def _split_top(inner):
    elems, depth, cur, in_s, q = [], 0, "", False, None
    for ch in inner:
        if in_s:
            cur += ch
            if q == '"' and ch == "\\":
                pass
            elif ch == q:
                in_s = False
            continue
        if ch == '"' or ch == "'":
            in_s, q = True, ch
            cur += ch
        elif ch in ("[", "{"):
            depth += 1
            cur += ch
        elif ch in ("]", "}"):
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            elems.append(cur)
            cur = ""
        else:
            cur += ch
    elems.append(cur)
    return elems, depth


def _validate_scalar(v, line_idx, ctx):
    v = v.strip()
    if not v:
        raise ValueError(f"Line {line_idx}: missing value {ctx}")
    if v[0] in "\"'":
        q = v[0]
        end = _close_quote(v, q)
        if end is None:
            raise ValueError(f"Line {line_idx}: unterminated string {ctx}")
        rem = v[end + 1:].strip()
        if rem:
            raise ValueError(f"Line {line_idx}: unexpected trailing content after string {ctx}")
        if q == '"' and not _validate_basic_string_inner(v[1:end]):
            raise ValueError(f"Line {line_idx}: invalid escape sequence in basic string {ctx}")
        return v[1:end]
    if v in ("true", "false"):
        return v == "true"
    if v[0] == "[":
        return _validate_array(v, line_idx, ctx)
    if v[0] == "{":
        return _validate_inline_table(v, line_idx, ctx)
    if INT_RE.fullmatch(v):
        if re.match(r"[+-]?0[xob]", v, re.I):
            return int(v.replace("_", ""), 0)
        return int(v.replace("_", ""))
    if FLOAT_RE.fullmatch(v):
        return float(v.replace("_", ""))
    if DATETIME_RE.fullmatch(v):
        return v
    raise ValueError(f"Line {line_idx}: invalid TOML value for {ctx}: {v!r}")


def _validate_array(v, line_idx, ctx):
    s = v.strip()
    if not s.endswith("]"):
        raise ValueError(f"Line {line_idx}: unclosed or multi-line array not supported by fallback validator {ctx}: {s!r}")
    inner = s[1:-1].strip()
    if inner == "":
        return []
    elems, depth = _split_top(inner)
    if depth != 0:
        raise ValueError(f"Line {line_idx}: unbalanced array {ctx}")
    if len(elems) > 1 and elems[-1].strip() == "":
        raise ValueError(f"Line {line_idx}: trailing comma not allowed in TOML array {ctx}")
    for e in elems:
        _validate_scalar(e, line_idx, ctx)
    return s


def _validate_inline_table(v, line_idx, ctx):
    s = v.strip()
    if not s.endswith("}"):
        raise ValueError(f"Line {line_idx}: unclosed or multi-line inline table not supported by fallback validator {ctx}: {s!r}")
    inner = s[1:-1].strip()
    if inner == "":
        return {}
    pairs, depth = _split_top(inner)
    if depth != 0:
        raise ValueError(f"Line {line_idx}: unbalanced inline table {ctx}")
    if len(pairs) > 1 and pairs[-1].strip() == "":
        raise ValueError(f"Line {line_idx}: trailing comma not allowed in inline table {ctx}")
    seen = set()
    for p in pairs:
        pp = p.strip()
        if pp == "":
            continue
        if "=" not in pp:
            raise ValueError(f"Line {line_idx}: inline table entry missing '=' {ctx}: {pp!r}")
        k, val = pp.split("=", 1)
        k_norm = k.strip()
        if not _valid_key(k_norm):
            raise ValueError(f"Line {line_idx}: invalid inline table key {k_norm!r} {ctx}")
        if k_norm in seen:
            raise ValueError(f"Line {line_idx}: duplicate key '{k_norm}' in inline table {ctx}")
        seen.add(k_norm)
        _validate_scalar(val, line_idx, ctx)
    return s


def strict_toml_validate(content):
    """Return root-level parsed dict; raise ValueError on any malformed TOML."""
    root_config = {}
    table_keysets = {}
    declared_tables = set()
    current_table = None
    for line_idx, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            if line.startswith("[["):
                if not line.endswith("]]") or len(line) <= 4:
                    raise ValueError(f"Line {line_idx}: malformed array-of-tables header: {raw}")
                current_table = line[2:-2].strip()
            else:
                if not line.endswith("]") or len(line) <= 2:
                    raise ValueError(f"Line {line_idx}: malformed table header: {raw}")
                current_table = line[1:-1].strip()
            if not _valid_key(current_table):
                raise ValueError(f"Line {line_idx}: invalid table key in header: {current_table!r}")
            if not line.startswith("[["):
                if current_table in declared_tables:
                    raise ValueError(f"Line {line_idx}: duplicate table header [{current_table}]")
                declared_tables.add(current_table)
            table_keysets.setdefault(current_table, set())
            continue
        if "=" not in line:
            raise ValueError(f"Line {line_idx}: expected key = value, got: {line!r}")
        key_part, val_part = line.split("=", 1)
        key = key_part.strip()
        val = _rstrip_comment(val_part).strip()
        if not _valid_key(key):
            raise ValueError(f"Line {line_idx}: invalid key {key!r}")
        if not val:
            raise ValueError(f"Line {line_idx}: missing value after '=': {raw}")
        scope = current_table
        table_keysets.setdefault(scope, set())
        if key in table_keysets[scope]:
            where = "root" if scope is None else "table [" + str(scope) + "]"
            raise ValueError(f"Line {line_idx}: duplicate key '{key}' in {where}")
        table_keysets[scope].add(key)
        parsed = _validate_scalar(val, line_idx, "key '" + key + "'")
        if scope is None:
            root_config[key] = parsed
    if "model_provider" not in root_config:
        raise ValueError("config.toml missing model_provider configuration")
    mp = root_config["model_provider"]
    if not isinstance(mp, str) or not mp.strip():
        raise ValueError("config.toml missing model_provider configuration")
    return root_config


def main():
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

    data, used = _try_authoritative_parse(content)
    if data is not None:
        if not isinstance(data, dict):
            sys.exit("Parsed TOML is not a dictionary")
        if "model_provider" not in data:
            sys.exit("config.toml missing model_provider configuration")
        mp = data["model_provider"]
        if not isinstance(mp, str) or not mp.strip():
            sys.exit("config.toml missing model_provider configuration")
        sys.exit(0)

    # No supported parser available -> strict fail-closed fallback.
    try:
        strict_toml_validate(content)
    except ValueError as e:
        sys.exit(f"TOML validation failed: {e}")
    sys.exit(0)


main()
PYCODE
}

SOURCE_DIR="${1:-${CODEX_SOURCE_DIR:-/etc/codex_source}}"
TARGET_DIR="${2:-${CODEX_HOME:-/root/.codex_pipeline}}"
TARGET_USER="${3:-$(id -u -n)}"

LINK="$TARGET_DIR"
STORE="${TARGET_DIR}.store"
LOCK_FILE="${TARGET_DIR}.lock"

# R2: Missing source / incomplete source fails closed unless a valid target
# runtime already exists (symlink or legacy directory), which is reused.
if [ ! -d "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/auth.json" ] || [ ! -f "$SOURCE_DIR/config.toml" ]; then
  if [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/auth.json" ] && [ -f "$TARGET_DIR/config.toml" ]; then
    if validate_err=$(validate_profile_dir "$TARGET_DIR" 2>&1); then
      echo "[$(date -u +%FT%TZ)] INIT INFO: Source $SOURCE_DIR missing/incomplete, but valid target profile exists at $TARGET_DIR. Reusing existing runtime."
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

# Do not replace an existing valid profile unless explicitly refreshing.
if [ -d "$TARGET_DIR" ] && ([ -e "$TARGET_DIR/auth.json" ] || [ -e "$TARGET_DIR/config.toml" ]) && [ "${REFRESH_CODEX_PROFILE:-0}" != "1" ]; then
  if ! validate_err=$(validate_profile_dir "$TARGET_DIR" 2>&1); then
    echo "[$(date -u +%FT%TZ)] INIT ERROR: Existing target profile is invalid: $validate_err" >&2
    exit 1
  fi
  echo "[$(date -u +%FT%TZ)] INIT INFO: Existing target profile at $TARGET_DIR is valid and REFRESH_CODEX_PROFILE!=1. Skipping replacement."
  exit 0
fi

# Ensure the parent of the link is present and owned by the target user.
PARENT_DIR="$(dirname "$LINK")"
mkdir -p "$PARENT_DIR"
chown "$TARGET_USER" "$PARENT_DIR" 2>/dev/null || true
mkdir -p "$STORE"
chmod 700 "$STORE"
chown "$TARGET_USER" "$STORE"

# R3: Writer serialization via non-blocking flock. The lock file is a stable
# sibling of the link (its path does not follow the changing symlink target).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -u +%FT%TZ)] ERROR: Another profile initialization is running for $TARGET_DIR" >&2
  exit 1
fi

NEWGEN=""
TMP_LINK=""
OLDGEN=""
LEGACY_GEN=""

cleanup() {
  local ec=$?
  # On any failure, remove an unpublished generation and any temp symlink, but
  # NEVER remove the live generation or the retained previous one.
  if [ "$ec" -ne 0 ]; then
    # Rollback: if we migrated a legacy real directory away but failed to
    # publish the symlink, the canonical $LINK path is now missing. Restore
    # the legacy directory back to $LINK so readers keep a usable profile.
    if [ -n "${LEGACY_GEN:-}" ] && [ -d "$LEGACY_GEN" ] && [ ! -e "$LINK" ] && [ ! -L "$LINK" ]; then
      echo "[$(date -u +%FT%TZ)] ROLLBACK: Restoring legacy directory from $LEGACY_GEN to $LINK" >&2
      mv "$LEGACY_GEN" "$LINK" || true
    fi
    live="$(readlink "$LINK" 2>/dev/null || true)"
    if [ -n "${NEWGEN:-}" ] && [ -d "$NEWGEN" ] && [ "$NEWGEN" != "$live" ]; then
      rm -rf "$NEWGEN" || true
    fi
    [ -n "${TMP_LINK:-}" ] && [ -e "$TMP_LINK" ] && rm -f "$TMP_LINK" || true
  fi
  exit "$ec"
}
trap cleanup EXIT INT TERM

# Build the new generation fully before publishing.
GEN_ID="gen_$(date -u +%Y%m%d%H%M%S)_$$"
NEWGEN="$STORE/$GEN_ID"
mkdir -p "$NEWGEN"
chmod 700 "$NEWGEN"
chown "$TARGET_USER" "$NEWGEN"

cp -a "$SOURCE_DIR/auth.json" "$NEWGEN/auth.json"
if [ -f "$SOURCE_DIR/config.toml" ]; then
  cp -a "$SOURCE_DIR/config.toml" "$NEWGEN/config.toml"
fi
if [ -f "$SOURCE_DIR/version.json" ]; then
  cp -a "$SOURCE_DIR/version.json" "$NEWGEN/version.json"
fi
if [ -f "$SOURCE_DIR/models_cache.json" ]; then
  cp -a "$SOURCE_DIR/models_cache.json" "$NEWGEN/models_cache.json"
fi

chown -R "$TARGET_USER" "$NEWGEN"
chmod 600 "$NEWGEN"/* 2>/dev/null || true

# Validate the complete staged generation before activation.
if ! validate_err=$(validate_profile_dir "$NEWGEN" 2>&1); then
  echo "[$(date -u +%FT%TZ)] ERROR: $validate_err" >&2
  exit 1
fi

# Capture the current live generation (for retention/rollback) before republishing.
OLDGEN="$(readlink "$LINK" 2>/dev/null || true)"
if [ -d "$LINK" ] && [ ! -L "$LINK" ]; then
  # Legacy real-directory target: migrate it into the store as a retained gen.
  LEGACY_GEN="$STORE/gen_legacy_$$_$(date -u +%Y%m%d%H%M%S)"
  if ! mv "$LINK" "$LEGACY_GEN"; then
    echo "[$(date -u +%FT%TZ)] ERROR: Failed to migrate legacy profile directory to $LEGACY_GEN" >&2
    LEGACY_GEN=""
    exit 1
  fi
  chmod 700 "$LEGACY_GEN"
  chown "$TARGET_USER" "$LEGACY_GEN"
  OLDGEN="$LEGACY_GEN"
fi

# Atomic, reader-consistent publish: build the pointer at a sibling temp name,
# then rename(2) it over $LINK. Readers always see a complete generation.
TMP_LINK="${LINK}.tmp_$$"
if ! ln -s "$NEWGEN" "$TMP_LINK"; then
  echo "[$(date -u +%FT%TZ)] ERROR: Failed to create temp symlink $TMP_LINK" >&2
  TMP_LINK=""
  exit 1
fi
if ! mv -T "$TMP_LINK" "$LINK"; then
  echo "[$(date -u +%FT%TZ)] ERROR: Failed to publish profile symlink for $TARGET_DIR" >&2
  # cleanup trap will restore LEGACY_GEN if it is set, so $LINK never goes missing.
  exit 1
fi
# Publish succeeded; clear LEGACY_GEN so a later failure does not attempt a
# now-obsolete rollback into a path that is now a valid symlink.
LEGACY_GEN=""
TMP_LINK=""

# Prune superseded generations, retaining a retention buffer (the new live gen,
# the immediately-previous gen as the primary rollback point, plus additional
# recent generations) so that concurrent long-running readers across successive
# rapid refreshes never hit a removed generation (ENOENT).
GEN_RETENTION_COUNT=5
prune_old_gens() {
  local keep_new="$1" d count
  # Build a timestamp-sorted list of all regular generation dirs (excludes
  # gen_legacy_* migration artifacts which are retained for rollback).
  local gens=()
  for d in "$STORE"/gen_*; do
    [ -d "$d" ] || continue
    case "$d" in
      "$STORE"/gen_legacy_*) continue ;;
    esac
    gens+=("$d")
  done
  # Sort by name (gen_<ts>_<pid> => chronological). Keep newest N.
  local sorted
  if [ ${#gens[@]} -eq 0 ]; then
    return 0
  fi
  printf '%s\n' "${gens[@]}" | sort -r | (count=0; while IFS= read -r d; do
    count=$((count + 1))
    if [ "$count" -le "$GEN_RETENTION_COUNT" ] || [ "$d" = "$keep_new" ]; then
      :
    else
      rm -rf "$d" || true
    fi
  done)
}
prune_old_gens "$NEWGEN"

# The live + retained generations are safe; clear the failure trap.
NEWGEN=""
TMP_LINK=""
trap - EXIT INT TERM

echo "[$(date -u +%FT%TZ)] SUCCESS: Profile activated at $LINK -> $(readlink "$LINK") for user $TARGET_USER"
