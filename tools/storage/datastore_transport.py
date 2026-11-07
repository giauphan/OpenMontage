from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() != name:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        return val
    return None


def _load_service_account() -> dict[str, Any]:
    value = _env_value("FIREBASE_SERVICE_ACCOUNT")
    if not value:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT is missing in .env; add it or provide requested Firebase config.")

    text = value.strip()
    if text.startswith("file://"):
        text = text[7:]

    path = Path(text).expanduser()
    if path.is_file():
        info = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            info = json.loads(text)
        except json.JSONDecodeError:
            padding = "=" * (-len(text) % 4)
            try:
                info = json.loads(base64.b64decode(text + padding).decode("utf-8"))
            except Exception as exc:
                raise RuntimeError(
                    "FIREBASE_SERVICE_ACCOUNT must be service account JSON, base64 JSON, or a JSON file path."
                ) from exc

    if not info.get("project_id"):
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT has no project_id; provide valid Firebase service account config.")
    return info


def _to_firestore_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_firestore_value(v) for k, v in value.items() if v is not None}}}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_to_firestore_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _from_firestore_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "mapValue" in value:
        return {k: _from_firestore_value(v) for k, v in value.get("mapValue", {}).get("fields", {}).items()}
    if "arrayValue" in value:
        return [_from_firestore_value(v) for v in value.get("arrayValue", {}).get("values", [])]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "nullValue" in value:
        return None
    return None


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    return {k: _to_firestore_value(v) for k, v in data.items() if v is not None}


def _decode_document(document: dict[str, Any]) -> dict[str, Any]:
    return {k: _from_firestore_value(v) for k, v in document.get("fields", {}).items()}
