"""Strict TOML fallback validator and Codex profile / home directory validation.

Validates config.toml without external runtime dependencies, ensuring well-formed
TOML syntax and valid root-level model_provider. Also validates CODEX_HOME structure,
auth.json credentials, and write permissions.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

# Strict single-line TOML fallback validator regexes
_TOML_INT_RE = re.compile(r"[+-]?(?:0[xob][\da-fA-F_]+|0|[1-9](?:_?\d)*)")
_TOML_FLOAT_RE = re.compile(
    r"[+-]?(?:\d[\d_]*(?:\.[\d_]+(?:e[+-]?[\d_]+)?|e[+-]?[\d_]+)|inf|nan)",
    re.IGNORECASE,
)
_TOML_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.+-]+Z?)?",
    re.IGNORECASE,
)
_TOML_KEY_SEG_RE = re.compile(r"[A-Za-z0-9_-]+")

ERR_MISSING_MODEL_PROVIDER = "Missing required root-level 'model_provider' in config.toml"
ERR_INVALID_MODEL_PROVIDER = (
    "Invalid root-level 'model_provider' in config.toml: must be a non-empty string"
)


def _toml_close_quote(s: str, q: str) -> Optional[int]:
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


def _is_hex_digits(s: str) -> bool:
    return len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)


def _validate_escape(inner: str, i: int, n: int) -> tuple[bool, int]:
    if i + 1 >= n:
        return False, 0
    esc = inner[i + 1]
    if esc in 'btnfr"\\':
        return True, 2
    if esc == "u":
        valid = (i + 6 <= n) and _is_hex_digits(inner[i + 2 : i + 6])
        return valid, 6
    if esc == "U":
        valid = (i + 10 <= n) and _is_hex_digits(inner[i + 2 : i + 10])
        return valid, 10
    return False, 0


def _toml_validate_basic_string_inner(inner: str) -> bool:
    i, n = 0, len(inner)
    while i < n:
        if inner[i] != "\\":
            i += 1
            continue
        ok, step = _validate_escape(inner, i, n)
        if not ok:
            return False
        i += step
    return True


def _toml_rstrip_comment(v: str) -> str:
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


def _toml_valid_key(k: str) -> bool:
    if not k:
        return False
    if k[0] in "\"'":
        end = _toml_close_quote(k, k[0])
        return end is not None and end == len(k) - 1
    parts = k.split(".")
    if any(p == "" for p in parts):
        return False
    return len(parts) >= 1 and all(_TOML_KEY_SEG_RE.fullmatch(p) for p in parts)


def _handle_toml_in_string(ch: str, q: Optional[str], esc: bool) -> tuple[bool, bool]:
    if esc:
        return True, False
    if q == '"' and ch == "\\":
        return True, True
    if ch == q:
        return False, False
    return True, False


def _toml_split_top(inner: str):
    elems: list[str] = []
    depth = 0
    cur = ""
    in_s, q, esc = False, None, False
    for ch in inner:
        if in_s:
            cur += ch
            in_s, esc = _handle_toml_in_string(ch, q, esc)
            continue
        if ch in ('"', "'"):
            in_s, q = True, ch
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        elif ch == "," and depth == 0:
            elems.append(cur)
            cur = ""
            continue
        cur += ch
    elems.append(cur)
    return elems, depth


def _toml_validate_string_scalar(v: str, line_idx: int, ctx: str) -> str:
    q = v[0]
    end = _toml_close_quote(v, q)
    if end is None:
        raise ValueError(f"Line {line_idx}: unterminated string {ctx}")
    rem = v[end + 1 :].strip()
    if rem:
        raise ValueError(f"Line {line_idx}: unexpected trailing content after string {ctx}")
    if q == '"' and not _toml_validate_basic_string_inner(v[1:end]):
        raise ValueError(f"Line {line_idx}: invalid escape sequence in basic string {ctx}")
    return v[1:end]


def _toml_validate_scalar(v: str, line_idx: int, ctx: str):
    v = v.strip()
    if not v:
        raise ValueError(f"Line {line_idx}: missing value {ctx}")
    if v[0] in "\"'":
        return _toml_validate_string_scalar(v, line_idx, ctx)
    if v in ("true", "false"):
        return v == "true"
    if v[0] == "[":
        return _toml_validate_array(v, line_idx, ctx)
    if v[0] == "{":
        return _toml_validate_inline_table(v, line_idx, ctx)
    if _TOML_INT_RE.fullmatch(v):
        if re.match(r"[+-]?0[xob]", v, re.I):
            return int(v.replace("_", ""), 0)
        return int(v.replace("_", ""))
    if _TOML_FLOAT_RE.fullmatch(v):
        return float(v.replace("_", ""))
    if _TOML_DATETIME_RE.fullmatch(v):
        return v
    raise ValueError(f"Line {line_idx}: invalid TOML value for {ctx}: {v!r}")


def _toml_validate_array(v: str, line_idx: int, ctx: str):
    s = v.strip()
    if not s.endswith("]"):
        raise ValueError(
            f"Line {line_idx}: unclosed or multi-line array not supported by fallback validator {ctx}: {s!r}"
        )
    inner = s[1:-1].strip()
    if inner == "":
        return []
    elems, depth = _toml_split_top(inner)
    if depth != 0:
        raise ValueError(f"Line {line_idx}: unbalanced array {ctx}")
    if len(elems) > 1 and elems[-1].strip() == "":
        raise ValueError(f"Line {line_idx}: trailing comma not allowed in TOML array {ctx}")
    for e in elems:
        _toml_validate_scalar(e, line_idx, ctx)
    return s


def _toml_validate_inline_table(v: str, line_idx: int, ctx: str):
    s = v.strip()
    if not s.endswith("}"):
        raise ValueError(
            f"Line {line_idx}: unclosed or multi-line inline table not supported by fallback validator {ctx}: {s!r}"
        )
    inner = s[1:-1].strip()
    if inner == "":
        return {}
    pairs, depth = _toml_split_top(inner)
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
        if not _toml_valid_key(k_norm):
            raise ValueError(f"Line {line_idx}: invalid inline table key {k_norm!r} {ctx}")
        if k_norm in seen:
            raise ValueError(f"Line {line_idx}: duplicate key '{k_norm}' in inline table {ctx}")
        seen.add(k_norm)
        _toml_validate_scalar(val, line_idx, ctx)
    return s


def _validate_model_provider(root_config: dict) -> None:
    if "model_provider" not in root_config:
        raise ValueError(ERR_MISSING_MODEL_PROVIDER)
    mp = root_config["model_provider"]
    if not isinstance(mp, str) or not mp.strip():
        raise ValueError(ERR_INVALID_MODEL_PROVIDER)


def _handle_table_header(
    line: str,
    raw: str,
    line_idx: int,
    declared_tables: set,
    table_keysets: Dict[Optional[str], set],
) -> str:
    if line.startswith("[["):
        if not line.endswith("]]") or len(line) <= 4:
            raise ValueError(f"Line {line_idx}: malformed array-of-tables header: {raw}")
        table_name = line[2:-2].strip()
    else:
        if not line.endswith("]") or len(line) <= 2:
            raise ValueError(f"Line {line_idx}: malformed table header: {raw}")
        table_name = line[1:-1].strip()

    if not _toml_valid_key(table_name):
        raise ValueError(f"Line {line_idx}: invalid table key in header: {table_name!r}")
    if not line.startswith("[["):
        if table_name in declared_tables:
            raise ValueError(f"Line {line_idx}: duplicate table header [{table_name}]")
        declared_tables.add(table_name)
    table_keysets.setdefault(table_name, set())
    return table_name


def _handle_toml_kv_line(
    line: str,
    raw: str,
    line_idx: int,
    current_table: Optional[str],
    table_keysets: Dict[Optional[str], set],
    root_config: Dict[str, object],
) -> None:
    if "=" not in line:
        raise ValueError(f"Line {line_idx}: expected key = value, got: {line!r}")
    key_part, val_part = line.split("=", 1)
    key = key_part.strip()
    val = _toml_rstrip_comment(val_part).strip()
    if not _toml_valid_key(key):
        raise ValueError(f"Line {line_idx}: invalid key {key!r}")
    if not val:
        raise ValueError(f"Line {line_idx}: missing value after '=': {raw}")

    table_keysets.setdefault(current_table, set())
    if key in table_keysets[current_table]:
        where = "root" if current_table is None else f"table [{current_table}]"
        raise ValueError(f"Line {line_idx}: duplicate key '{key}' in {where}")
    table_keysets[current_table].add(key)
    parsed = _toml_validate_scalar(val, line_idx, f"key '{key}'")
    if current_table is None:
        root_config[key] = parsed


def _strict_toml_validate(content: str) -> dict:
    """Return root-level parsed dict; raise ValueError on any malformed TOML."""
    root_config: Dict[str, object] = {}
    table_keysets: Dict[Optional[str], set] = {}
    declared_tables = set()
    current_table = None
    for line_idx, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current_table = _handle_table_header(line, raw, line_idx, declared_tables, table_keysets)
            continue
        _handle_toml_kv_line(line, raw, line_idx, current_table, table_keysets, root_config)

    _validate_model_provider(root_config)
    return root_config


def _load_toml_parser():
    try:
        import tomllib

        return tomllib.loads
    except ImportError:
        pass
    try:
        import tomli

        return tomli.loads
    except ImportError:
        return None


def parse_and_validate_config_toml(content: str) -> dict:
    """Parse and validate config.toml ensuring well-formed TOML and valid root-level model_provider."""
    parser = _load_toml_parser()
    if parser is not None:
        try:
            data = parser(content)
        except Exception as exc:
            raise ValueError(f"Invalid TOML syntax: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Parsed TOML is not a dictionary")
        _validate_model_provider(data)
        return data

    return _strict_toml_validate(content)


def _validate_profile_dir(profile_path: Path) -> None:
    """Validate that profile_path contains valid auth.json, config.toml, and required credentials."""
    auth_file = profile_path / "auth.json"
    if not auth_file.is_file() or auth_file.stat().st_size == 0:
        raise RuntimeError(f"Configured CODEX_HOME is missing or has empty auth.json: {profile_path}")
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Configured CODEX_HOME has invalid JSON in auth.json: {profile_path}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Configured CODEX_HOME auth.json is not a JSON object: {profile_path}")

    api_key = data.get("OPENAI_API_KEY")
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError(f"Configured CODEX_HOME auth.json missing or invalid OPENAI_API_KEY: {profile_path}")

    config_file = profile_path / "config.toml"
    if not config_file.is_file() or config_file.stat().st_size == 0:
        raise RuntimeError(f"Configured CODEX_HOME is missing or has empty config.toml: {profile_path}")

    try:
        config_content = config_file.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Configured CODEX_HOME could not read config.toml: {profile_path}") from exc

    try:
        parse_and_validate_config_toml(config_content)
    except Exception as exc:
        raise RuntimeError(
            f"Configured CODEX_HOME config.toml is invalid or missing model_provider: {profile_path} ({exc})"
        ) from exc


def resolve_and_validate_codex_home(env: Optional[Dict[str, str]] = None) -> str:
    """Resolve and validate the active CODEX_HOME directory."""
    if env is None:
        env = os.environ

    explicit_home = env.get("CODEX_HOME")
    if explicit_home and explicit_home.strip():
        home_path = Path(explicit_home.strip()).resolve()
        if not home_path.is_dir():
            raise RuntimeError(f"Configured CODEX_HOME does not exist or is not a directory: {home_path}")
        _validate_profile_dir(home_path)
        try:
            test_file = home_path / f".write_test_{os.getpid()}"
            test_file.touch()
            test_file.unlink()
        except OSError as exc:
            raise RuntimeError(f"Configured CODEX_HOME is not writable: {home_path} ({exc})")
        return str(home_path)

    candidate_homes = [
        Path.home() / ".codex_pipeline",
        Path("/root/.codex_pipeline"),
        Path.home() / ".codex",
        Path("/root/.codex"),
        Path("/home/ubuntu/.codex"),
    ]
    for ch in candidate_homes:
        try:
            resolved_ch = ch.resolve()
            _validate_profile_dir(resolved_ch)
            test_file = resolved_ch / f".write_test_{os.getpid()}"
            test_file.touch()
            test_file.unlink()
            return str(resolved_ch)
        except (RuntimeError, OSError):
            continue

    raise RuntimeError(
        "No valid Codex home with non-empty auth.json, config.toml, and write permissions found, "
        "and CODEX_HOME is unset. Fallback to temporary credentials is disabled."
    )


__all__ = [
    "_TOML_INT_RE",
    "_TOML_FLOAT_RE",
    "_TOML_DATETIME_RE",
    "_TOML_KEY_SEG_RE",
    "_toml_close_quote",
    "_toml_validate_basic_string_inner",
    "_toml_rstrip_comment",
    "_toml_valid_key",
    "_toml_split_top",
    "_toml_validate_scalar",
    "_toml_validate_array",
    "_toml_validate_inline_table",
    "_strict_toml_validate",
    "parse_and_validate_config_toml",
    "_validate_profile_dir",
    "resolve_and_validate_codex_home",
]
