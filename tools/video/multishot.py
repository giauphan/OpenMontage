"""Multishot orchestration tool for the OpenMontage pipeline.

Experimental integration of multi-shot capabilities into the public tool registry.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Dict

from lib.multishot_session import MultishotSession
from lib.multishot_workspace import init_multishot_project, REPORTS_DIR
from lib.multishot_continuity import snapshot
from lib.multishot_finalize_operations import finalize_session, validate_completion
from lib.media_profiles import AspectRatio, MediaProfile

from tools.base_tool import (
    BaseTool,
    ToolResult,
    ToolStability,
    ToolTier,
    ExecutionMode,
    Determinism,
    ToolRuntime,
    ResourceProfile,
    RetryPolicy,
    ResumeSupport
)

class Multishot(BaseTool):
    name = "multishot"
    version = "0.1.0"
    tier = ToolTier.CORE
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    install_instructions = "Built-in."
    capability = "multishot_orchestration"
    provider = "openmontage"
    capabilities = ["init", "status", "prepare_shot", "bind_input", "bind_job_spec", "record_result", "review", "regenerate", "invalidate_reference", "checkpoint", "finalize", "validate_completion", "generate"]

    input_schema = {
        "type": "object",
        "required": ["operation", "project_id"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["init", "status", "prepare_shot", "bind_input", "bind_job_spec", "record_result", "review", "regenerate", "invalidate_reference", "checkpoint", "finalize", "validate_completion", "generate"]
            },
            "project_id": {
                "type": "string",
                "pattern": "^[-_a-zA-Z0-9]+$"
            },
            "shot_id": {
                "type": "string",
                "pattern": "^[-_a-zA-Z0-9]+$"
            }
        },
        "additionalProperties": True
    }

    def __init__(self, provider_factory: Optional[Callable[[], Any]] = None):
        self._provider_factory = provider_factory

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation")

        try:
            if operation == "init":
                return self._init(inputs)
            elif operation == "status":
                return self._status(inputs)
            elif operation == "prepare_shot":
                return self._prepare_shot(inputs)
            elif operation == "bind_input":
                return self._bind_input(inputs)
            elif operation == "bind_job_spec":
                return self._bind_job_spec(inputs)
            elif operation == "record_result":
                return self._record_result(inputs)
            elif operation == "review":
                return self._review(inputs)
            elif operation == "regenerate":
                return self._regenerate(inputs)
            elif operation == "invalidate_reference":
                return self._invalidate_reference(inputs)
            elif operation == "checkpoint":
                return self._checkpoint(inputs)
            elif operation == "finalize":
                return self._finalize(inputs)
            elif operation == "validate_completion":
                return self._validate_completion(inputs)
            elif operation == "generate":
                return self._generate(inputs)
            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}")
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Internal error: {str(e)}")

    def _get_project_dir(self, inputs: dict[str, Any]) -> Path:
        import re
        project_id = inputs["project_id"]
        if not re.match(r"^[-_a-zA-Z0-9]+$", project_id):
            raise ValueError("Unsafe project_id")

        if "root_dir" in inputs:
            root_dir = Path(inputs["root_dir"]).resolve()
        else:
            from lib.paths import PROJECTS_DIR
            root_dir = PROJECTS_DIR.resolve()

        project_path = root_dir / project_id
        if project_path.is_symlink():
            raise ValueError("Unsafe project directory symlink")

        project_dir = project_path.resolve()
        try:
            project_dir.relative_to(root_dir)
        except ValueError as exc:
            raise ValueError("Project directory escaping root") from exc

        return project_dir

    def _validate_project_marker(self, project_dir: Path):
        """Validate project marker exists and identifies a multi-shot project."""
        marker_path = project_dir / "project.json"
        if not marker_path.is_file():
            raise ValueError("Project marker missing, project not initialized")

        try:
            with marker_path.open(encoding="utf-8") as marker_file:
                marker = json.load(marker_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Project marker is not readable JSON") from exc

        if (
            not isinstance(marker, dict)
            or marker.get("project_id") != project_dir.name
            or marker.get("pipeline_type") != "multi-shot"
        ):
            raise ValueError("Project marker identity mismatch")

    def _init(self, inputs: dict[str, Any]) -> ToolResult:
        project_id = inputs["project_id"]
        title = inputs.get("title", project_id)
        planning_artifacts = inputs.get("planning_artifacts")

        if not planning_artifacts:
            return ToolResult(success=False, error="planning_artifacts required for init")

        root_dir = inputs.get("root_dir")
        if root_dir:
            project_dir = init_multishot_project(project_id, title=title, pipeline_dir=Path(root_dir))
        else:
            project_dir = init_multishot_project(project_id, title=title)

        session = MultishotSession(project_dir)
        session.initialize(planning_artifacts)

        return ToolResult(
            success=True,
            data={"project_dir": str(project_dir), "status": "initialized"},
            artifacts=[str(session._path)]
        )

    def _status(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        session = MultishotSession(project_dir)
        state = session.get_state()

        return ToolResult(
            success=True,
            data=state
        )

    def _prepare_shot(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        project_id = inputs["project_id"]
        shot_id = inputs.get("shot_id")
        reference_store = inputs.get("reference_store", {})
        reference_review = inputs.get("reference_review")

        if not shot_id:
            return ToolResult(success=False, error="shot_id required")
        if not reference_review or not isinstance(reference_review.get("approved"), bool) or not reference_review.get("reviewer"):
            return ToolResult(success=False, error="Explicit reference_review required with boolean 'approved' and string 'reviewer'")

        if not reference_review["approved"]:
            return ToolResult(success=False, error=f"Shot preparation rejected by reference review notes: {reference_review.get('notes', 'No notes provided')}")

        session = MultishotSession(project_dir)

        prepared = session.prepare_shot_prompt(shot_id, reference_store, reference_review)

        return ToolResult(
            success=True,
            data={
                "prompt": prepared["prompt"],
                "references": prepared["references"],
                "shot": prepared["shot"],
            }
        )

    def _generate(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.multishot_generation import execute_generation

        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        provider = inputs.get("provider")
        model = inputs.get("model")
        settings = inputs.get("settings")
        spend_approved = inputs.get("spend_approved")
        budget_usd = inputs.get("budget_usd")
        estimated_usd = inputs.get("estimated_usd")
        reference_store = inputs.get("reference_store")
        reference_review = inputs.get("reference_review")

        if not shot_id or not provider or not model or settings is None or spend_approved is None or budget_usd is None or estimated_usd is None or reference_store is None or reference_review is None:
            return ToolResult(
                success=False,
                error="shot_id, provider, model, settings, spend_approved, budget_usd, estimated_usd, reference_store, and reference_review required"
            )

        kwargs = {
            "project_dir": project_dir,
            "shot_id": shot_id,
            "provider": provider,
            "model": model,
            "settings": settings,
            "spend_approved": spend_approved,
            "budget_usd": budget_usd,
            "estimated_usd": estimated_usd,
            "reference_store": reference_store,
            "reference_review": reference_review,
            "provider_factory": self._provider_factory,
        }

        for opt in ("deadline_seconds", "max_polls", "poll_interval"):
            if opt in inputs:
                kwargs[opt] = inputs[opt]

        res = execute_generation(**kwargs)
        status = res.get("status")
        if status == "completed":
            return ToolResult(success=True, data=res)
        else:
            return ToolResult(success=False, data=res, error=res.get("outcome", {}).get("error", f"Generation status: {status}"))

    def _bind_input(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        prompt = inputs.get("prompt")
        references = inputs.get("references", [])

        if not shot_id or prompt is None:
            return ToolResult(success=False, error="shot_id and prompt required")

        session = MultishotSession(project_dir)
        bound = session.bind_input(shot_id, prompt, references)

        return ToolResult(
            success=True,
            data={"shot": bound}
        )

    def _bind_job_spec(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        revision = inputs.get("revision")
        spec_dict = inputs.get("job_spec")

        if not shot_id or revision is None or not spec_dict:
            return ToolResult(success=False, error="shot_id, revision, and job_spec required")

        session = MultishotSession(project_dir)
        bound = session.bind_job_spec(shot_id, revision, spec_dict)

        return ToolResult(
            success=True,
            data={"shot": bound}
        )

    def _record_result(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        revision = inputs.get("revision")
        outcome = inputs.get("outcome")

        if not shot_id or revision is None or not outcome:
            return ToolResult(success=False, error="shot_id, revision, and outcome required")

        session = MultishotSession(project_dir)
        recorded = session.record_result(shot_id, revision, outcome)

        return ToolResult(
            success=True,
            data={"shot": recorded}
        )

    def _review(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        revision = inputs.get("revision")
        accepted = inputs.get("accepted")
        if not isinstance(accepted, bool):
            return ToolResult(success=False, error="'accepted' must be a boolean")
        end_state = inputs.get("end_state")
        reviewer = inputs.get("reviewer")
        notes = inputs.get("notes")

        if not shot_id or revision is None or end_state is None or reviewer is None or notes is None:
            return ToolResult(success=False, error="shot_id, revision, accepted, end_state, reviewer, and notes required")

        session = MultishotSession(project_dir)
        reviewed = session.review_shot(shot_id, revision, accepted, end_state, reviewer, notes)

        return ToolResult(
            success=True,
            data={"shot": reviewed}
        )

    def _regenerate(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        shot_id = inputs.get("shot_id")
        end_state = inputs.get("end_state")

        if not shot_id:
            return ToolResult(success=False, error="shot_id required")

        session = MultishotSession(project_dir)
        stale_ids = session.regenerate_shot(shot_id, end_state)

        return ToolResult(
            success=True,
            data={"stale_ids": stale_ids}
        )

    def _invalidate_reference(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        reference_key = inputs.get("reference_key")

        if not reference_key:
            return ToolResult(success=False, error="reference_key required")

        session = MultishotSession(project_dir)
        stale_ids = session.invalidate_reference(reference_key)

        return ToolResult(
            success=True,
            data={"stale_ids": stale_ids}
        )

    def _profile_from_inputs(self, inputs: dict[str, Any]) -> MediaProfile:
        profile = inputs.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("profile must be a dict")
        required = {"name", "width", "height", "aspect_ratio", "fps", "codec", "audio_codec", "crf"}
        if not required.issubset(profile):
            raise ValueError("profile is missing required fields")
        try:
            values = dict(profile)
            values["aspect_ratio"] = AspectRatio(values["aspect_ratio"])
            return MediaProfile(**values)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("profile has invalid media profile fields") from exc

    def _finalize(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        profile = self._profile_from_inputs(inputs)
        evidence = finalize_session(
            project_dir,
            profile,
            narration=inputs.get("narration"),
            music=inputs.get("music"),
            sfx=inputs.get("sfx"),
            subtitles=inputs.get("subtitles"),
            burn_subtitles=inputs.get("burn_subtitles", False),
            ducking_threshold_db=inputs.get("ducking_threshold_db", -20.0),
            ducking_ratio=inputs.get("ducking_ratio", 5.0),
            audio_fade_in_sec=inputs.get("audio_fade_in_sec"),
            audio_fade_out_sec=inputs.get("audio_fade_out_sec"),
        )
        return ToolResult(
            success=True,
            data=evidence,
            artifacts=[
                evidence["final_path"],
                str(project_dir / REPORTS_DIR / "render_report.json"),
                str(project_dir / REPORTS_DIR / "final_review.json"),
            ],
        )

    def _validate_completion(self, inputs: dict[str, Any]) -> ToolResult:
        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        result = validate_completion(project_dir)
        return ToolResult(success=result["valid"], data=result, error=None if result["valid"] else result["reason"])

    def _checkpoint(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.checkpoint import write_checkpoint, CheckpointValidationError

        project_dir = self._get_project_dir(inputs)
        self._validate_project_marker(project_dir)
        project_id = inputs["project_id"]
        stage = inputs.get("stage")
        artifacts = inputs.get("artifacts")
        human_approved = inputs.get("human_approved", False)

        if not stage or artifacts is None:
            return ToolResult(success=False, error="stage and artifacts required")

        if stage == "compose":
            completion = validate_completion(project_dir)
            if not completion["valid"]:
                return ToolResult(
                    success=False,
                    error=f"Cannot complete compose: {completion['reason']}",
                    data=completion,
                )

        root_dir = inputs.get("root_dir")
        if root_dir:
            pipeline_dir = Path(root_dir).resolve()
        else:
            from lib.paths import PROJECTS_DIR
            pipeline_dir = PROJECTS_DIR.resolve()

        # We must use real pipeline manifest approval gates.
        # But we only need to call write_checkpoint which does all the validation for us.

        try:
            path = write_checkpoint(
                pipeline_dir=pipeline_dir,
                project_id=project_id,
                stage=stage,
                status="completed",
                artifacts=artifacts,
                pipeline_type="multi-shot",
                human_approved=human_approved
            )
            return ToolResult(success=True, data={"checkpoint_file": str(path)})
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
