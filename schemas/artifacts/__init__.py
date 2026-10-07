"""Artifact schema loading and validation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from schemas.multishot import MULTISHOT_ARTIFACT_NAMES

SCHEMA_DIR = Path(__file__).parent

ARTIFACT_NAMES = [
    "research_brief",
    "proposal_packet",
    "brief",
    "script",
    "character_design",
    "rig_plan",
    "pose_library",
    "scene_plan",
    "action_timeline",
    "asset_manifest",
    "edit_decisions",
    "render_report",
    "publish_log",
    "review",
    "cost_log",
    "decision_log",
    "source_media_review",
    "final_review",
    "character_qa_report",
    "video_analysis_brief",
] + MULTISHOT_ARTIFACT_NAMES


def load_schema(name: str) -> dict:
    """Load a JSON schema by artifact name."""
    if name in MULTISHOT_ARTIFACT_NAMES:
        from schemas.multishot import load_schema as load_multishot_schema
        return load_multishot_schema(name)
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_artifact(name: str, data: dict[str, Any]) -> None:
    """Validate artifact data against its schema. Raises on failure."""
    if name in MULTISHOT_ARTIFACT_NAMES:
        if not isinstance(data, dict):
            raise ValueError(f"Artifact {name!r} must be a JSON object")
        from lib.multishot_schemas import validate_all_cross
        if name == "run_manifest":
            # During generation the manifest is incrementally populated.
            from schemas.multishot import validate
            validate(name, data)
            if len(data["shots"]) > data["shot_count"]:
                raise ValueError("run_manifest has more shots than shot_count")
        else:
            validate_all_cross(**{name: data})
        return
    schema = load_schema(name)
    jsonschema.validate(instance=data, schema=schema)


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return sorted({p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")} | set(MULTISHOT_ARTIFACT_NAMES))
