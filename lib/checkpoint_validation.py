"""Validation logic for OpenMontage checkpoints and artifacts."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import jsonschema

from schemas.artifacts import ARTIFACT_NAMES, validate_artifact

CHECKPOINT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "checkpoints"
    / "checkpoint.schema.json"
)

# All known stages across all pipelines (used only for artifact name lookup).
ALL_KNOWN_STAGES = frozenset([
    "research", "proposal", "idea", "script", "scene_plan",
    "assets", "edit", "compose", "publish",
])

CANONICAL_STAGE_ARTIFACTS = {
    "research": "research_brief",
    "proposal": "proposal_packet",
    "idea": "brief",
    "script": "script",
    "scene_plan": "scene_plan",
    "assets": "asset_manifest",
    "edit": "edit_decisions",
    "compose": "render_report",
    "publish": "publish_log",
}


class CheckpointValidationError(ValueError):
    """Raised when a checkpoint or its canonical artifacts are invalid."""


def _validate_style_playbook(style_playbook: str | None) -> None:
    """Fail closed when a checkpoint names a visual identity that cannot load."""
    if style_playbook is None:
        return
    try:
        from styles.playbook_loader import list_playbooks, load_playbook

        load_playbook(style_playbook)
    except Exception as exc:
        try:
            available = list_playbooks()
        except Exception:
            available = []
        raise CheckpointValidationError(
            f"Unknown or invalid style_playbook {style_playbook!r}. "
            f"Available playbooks: {available}. Underlying error: {exc}"
        ) from exc


@lru_cache(maxsize=1)
def _load_checkpoint_schema() -> dict[str, Any]:
    with open(CHECKPOINT_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _validate_artifacts_for_stage(
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    pipeline_type: str | None = None,
) -> None:
    required_artifact = CANONICAL_STAGE_ARTIFACTS.get(stage)
    if (
        required_artifact is not None
        and status in {"completed", "awaiting_human"}
        and required_artifact not in artifacts
    ):
        raise CheckpointValidationError(
            f"Stage {stage!r} with status {status!r} must include "
            f"canonical artifact {required_artifact!r}"
        )

    if pipeline_type == "multi-shot" and status in {"completed", "awaiting_human"}:
        from lib.pipeline_loader import load_pipeline_readonly
        manifest = load_pipeline_readonly(pipeline_type)
        definition = next(s for s in manifest["stages"] if s["name"] == stage)
        for name in definition.get("produces", []):
            if name not in artifacts:
                raise CheckpointValidationError(f"Stage {stage!r} must include artifact {name!r}")

    for artifact_name, artifact_data in artifacts.items():
        if artifact_name not in ARTIFACT_NAMES:
            if pipeline_type == "multi-shot":
                raise CheckpointValidationError(f"Unknown artifact {artifact_name!r}; register a schema first")
            continue
        if not isinstance(artifact_data, dict):
            raise CheckpointValidationError(
                f"Artifact {artifact_name!r} must be a JSON object matching its schema"
            )
        try:
            validate_artifact(artifact_name, artifact_data)
        except Exception as exc:
            raise CheckpointValidationError(
                f"Artifact {artifact_name!r} failed schema validation: {exc}"
            ) from exc

    _validate_hook_plan_status(stage, status, artifacts, pipeline_type)


def _validate_hook_plan_status(
    stage: str,
    status: str,
    artifacts: dict[str, Any],
    pipeline_type: str | None = None,
) -> None:
    try:
        from lib.hook_guard.config import load_hook_policy
        policy = load_hook_policy()
    except Exception:
        policy = None

    hook_plan = artifacts.get("hook_plan")
    policy_mode = policy.mode if policy else "off"

    if not policy or not policy.is_active():
        if not hook_plan:
            return

    is_hook_pipeline = False
    if pipeline_type:
        if pipeline_type == "clip-factory":
            is_hook_pipeline = True
        else:
            try:
                from lib.pipeline_loader import load_pipeline_readonly
                manifest = load_pipeline_readonly(pipeline_type)
                for st_def in manifest.get("stages", []) or []:
                    if isinstance(st_def, dict) and (
                        "hook_plan" in st_def.get("produces", [])
                        or "hook_plan" in st_def.get("optional_artifacts_in", [])
                        or "hook_plan" in st_def.get("required_artifacts_in", [])
                    ):
                        is_hook_pipeline = True
                        break
            except Exception:
                is_hook_pipeline = False
    else:
        is_hook_pipeline = bool(hook_plan)

    if not is_hook_pipeline and not hook_plan:
        return

    if policy_mode == "required" and stage == "edit" and status in {"completed", "awaiting_human"}:
        if not hook_plan:
            raise CheckpointValidationError(
                "HookGuard mode is 'required' but 'hook_plan' artifact is missing from edit stage."
            )
        guard_res = hook_plan.get("guard_result", {})
        if guard_res.get("status") != "PASS":
            raise CheckpointValidationError(
                f"HookGuard mode is 'required' but hook_plan status is {guard_res.get('status')!r} "
                f"({guard_res.get('reason_codes')})."
            )

    if hook_plan and status in {"completed", "awaiting_human"}:
        guard_res = hook_plan.get("guard_result", {})
        g_status = guard_res.get("status")
        if g_status == "REJECTED":
            raise CheckpointValidationError(
                f"Cannot advance stage with REJECTED hook_plan: {guard_res.get('reason_codes')}. "
                "In auto mode, rejected hooks must be skipped or reverted before checkpointing."
            )


def validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Validate checkpoint structure and canonical artifact payloads.

    Uses pipeline_type (if present) to resolve the valid stage list.
    Falls back to ALL_KNOWN_STAGES when pipeline_type is absent.
    """
    from lib.checkpoint import get_pipeline_stages

    stage = checkpoint.get("stage")
    status = checkpoint.get("status")
    artifacts = checkpoint.get("artifacts")
    pipeline_type = checkpoint.get("pipeline_type")

    valid_stages = (
        set(get_pipeline_stages(pipeline_type)) if pipeline_type
        else ALL_KNOWN_STAGES
    )

    if not isinstance(stage, str) or stage not in valid_stages:
        raise CheckpointValidationError(
            f"Invalid stage: {stage!r} for pipeline {pipeline_type!r}. "
            f"Valid stages: {sorted(valid_stages)}"
        )
    if not isinstance(status, str):
        raise CheckpointValidationError(f"Invalid status: {status!r}")
    if not isinstance(artifacts, dict):
        raise CheckpointValidationError("Checkpoint artifacts must be a dictionary")

    _validate_artifacts_for_stage(stage, status, artifacts, pipeline_type)

    try:
        jsonschema.validate(instance=checkpoint, schema=_load_checkpoint_schema())
    except jsonschema.ValidationError as exc:
        raise CheckpointValidationError(f"Checkpoint failed schema validation: {exc.message}") from exc
