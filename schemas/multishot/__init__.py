"""Multi-shot AI video pipeline — artifact schemas and validation helpers.

Schemas are versioned JSON Schema (draft 2020-12). Each file follows the
repository convention: "$id: openmontage/multishot/<name>", version field,
additionalProperties: false, and explicit minimum items on arrays.

The Python cross-field validator in lib/multishot_schemas.py handles
constraints that JSON Schema 2020-12 cannot express (unique id/order
uniqueness, FK checks, min_shots >= 2, contiguous order, duration
feasibility, non-finite number rejection).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_DIR = Path(__file__).parent

# Names of all multi-shot schemas shipped with this feature.
MULTISHOT_ARTIFACT_NAMES = [
    "request",
    "story",
    "character_bible",
    "style_bible",
    "shot_plan",
    "continuity_state",
    "job",
    "run_manifest",
]


def load_schema(name: str) -> dict:
    """Load a multi-shot JSON schema by artifact name.

    name: one of MULTISHOT_ARTIFACT_NAMES.
    """
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Multi-shot schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate(name: str, data: dict[str, Any]) -> None:
    """Validate a data dict against the named multi-shot schema. Raises on failure."""
    schema = load_schema(name)
    jsonschema.validate(instance=data, schema=schema)


def validate_all(data_by_name: dict[str, dict[str, Any]]) -> None:
    """Validate multiple named multi-shot artifacts in one call."""
    for name, data in data_by_name.items():
        if name not in MULTISHOT_ARTIFACT_NAMES:
            raise ValueError(f"Unknown multi-shot artifact name: {name!r}")
        validate(name, data)


def list_schemas() -> list[str]:
    """Return sorted list of available multi-shot schema names."""
    return sorted(p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json"))
