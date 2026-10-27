"""HyperFrames rendering engine adapter.

Delegates rendering to hyperframes_compose and runs post-render validation
with strict governance (no silent fallback).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import ToolResult


def render_via_hyperframes(
    tool: Any,
    *,
    inputs: dict[str, Any],
    edit_decisions: dict[str, Any],
    asset_manifest: dict[str, Any],
    resolved_cuts: list[dict],
    output_path: Path,
    profile: Optional[str],
) -> ToolResult:
    """Delegate to hyperframes_compose and run the mandatory final self-review.

    Governance: if HyperFrames is unavailable or fails, return a structured
    blocker — do NOT silently route to Remotion or FFmpeg. The agent must
    surface the blocker and get user approval before any runtime swap.
    """
    if not tool._hyperframes_available():
        return ToolResult(
            success=False,
            error=(
                "render_runtime='hyperframes' was locked at proposal, but "
                "the HyperFrames runtime is not available on this machine. "
                "Per governance this is a BLOCKER — surface it to the user "
                "per AGENT_GUIDE.md > 'Escalate Blockers Explicitly' and wait "
                "for approval before switching runtime. Requirements: "
                "Node.js >= 22, FFmpeg, and npx on PATH. See "
                "tools/video/hyperframes_compose.py for the specific missing piece."
            ),
        )

    try:
        from tools.video.hyperframes_compose import HyperFramesCompose
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Could not import hyperframes_compose: {e}",
        )

    workspace_path = (
        inputs.get("workspace_path")
        or str(output_path.parent.parent / "hyperframes")
    )

    playbook_data = inputs.get("playbook")
    if not playbook_data:
        playbook_name = (
            inputs.get("playbook_name")
            or (edit_decisions.get("metadata") or {}).get("playbook")
        )
        if playbook_name:
            try:
                from styles.playbook_loader import load_playbook  # type: ignore
                playbook_data = load_playbook(playbook_name)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Could not load style playbook %r for HyperFrames bridge: %s",
                    playbook_name,
                    exc,
                )
                playbook_data = None

    hf_inputs: dict[str, Any] = {
        "operation": "render",
        "workspace_path": workspace_path,
        "output_path": str(output_path),
        "edit_decisions": dict(edit_decisions, cuts=resolved_cuts),
        "asset_manifest": asset_manifest,
    }
    if playbook_data:
        hf_inputs["playbook"] = playbook_data
    if profile:
        hf_inputs["profile"] = profile
    if "quality" in inputs:
        hf_inputs["quality"] = inputs["quality"]
    if "fps" in inputs:
        hf_inputs["fps"] = inputs["fps"]
    if "strict" in inputs:
        hf_inputs["strict"] = inputs["strict"]
    if "skip_contrast" in inputs:
        hf_inputs["skip_contrast"] = inputs["skip_contrast"]
    if "preserve_existing_workspace" in inputs:
        hf_inputs["preserve_existing_workspace"] = inputs[
            "preserve_existing_workspace"
        ]

    render_result = HyperFramesCompose().execute(hf_inputs)

    if not render_result.success:
        return ToolResult(
            success=False,
            error=(
                f"HyperFrames render failed: {render_result.error}. "
                "Per governance: do NOT silently fall back to Remotion or "
                "FFmpeg. Surface the failure to the user along with the "
                "hyperframes_compose step log before proposing a swap."
            ),
            data=render_result.data,
        )

    if output_path.exists():
        final_review = tool._run_final_review(
            output_path,
            edit_decisions,
            inputs.get("proposal_packet"),
            narration_transcript_path=inputs.get("narration_transcript_path"),
            script_text=inputs.get("script_text") or tool._read_text_file(
                inputs.get("script_path")
            ),
        )
        if render_result.data is None:
            render_result.data = {}
        render_result.data["final_review"] = final_review
        render_result.data["final_review_status"] = final_review["status"]
        if final_review["status"] == "fail":
            return ToolResult(
                success=False,
                error=(
                    "Post-render self-review FAILED (HyperFrames). The output is not presentable.\n"
                    + "\n".join(f"  • {i}" for i in final_review.get("issues_found", []))
                ),
                data=render_result.data,
            )

    return render_result
