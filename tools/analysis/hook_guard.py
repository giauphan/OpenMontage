"""HookGuard tool wrapping deterministic structural, factuality, and invariant checks."""

from __future__ import annotations

from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)
from lib.hook_guard.config import load_hook_policy
from lib.hook_guard.guard import evaluate_hook_guard


class HookGuard(BaseTool):
    name = "hook_guard"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "hookguard"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []
    agent_skills = ["video-understand", "video-edit"]

    input_schema = {
        "type": "object",
        "required": ["candidate", "baseline_body_edl_sha256"],
        "properties": {
            "candidate": {"type": "object"},
            "baseline_body_edl_sha256": {"type": "string"},
            "mutated_edl": {"type": "object"},
            "render_runtime": {
                "type": "string",
                "enum": ["remotion", "hyperframes", "ffmpeg"],
                "default": "remotion",
            },
            "source_context": {"type": "object"},
            "video_duration": {"type": "number", "default": 60.0},
            "policy": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=5)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        candidate = inputs["candidate"]
        baseline_sha = inputs["baseline_body_edl_sha256"]
        mutated_edl = inputs.get("mutated_edl")
        render_runtime = inputs.get("render_runtime", "remotion")
        source_context = inputs.get("source_context", {})
        video_duration = float(inputs.get("video_duration", 60.0))

        policy_overrides = inputs.get("policy", {})
        policy = load_hook_policy(overrides=policy_overrides)

        guard_result = evaluate_hook_guard(
            candidate=candidate,
            policy=policy,
            baseline_body_edl_sha256=baseline_sha,
            mutated_edl=mutated_edl,
            render_runtime=render_runtime,
            source_context=source_context,
            video_duration=video_duration,
        )

        return ToolResult(
            success=True,
            data={"guard_result": guard_result},
        )
