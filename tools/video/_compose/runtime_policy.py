"""Composition runtime routing and governance policy.

Enforces fail-closed execution: proposal runtime must be respected,
silent engine swaps are strictly forbidden, and missing runtimes block render.
"""

from __future__ import annotations

from typing import Any, Optional, Set, Tuple

VALID_RUNTIMES: Set[str] = {"remotion", "hyperframes", "ffmpeg"}


def validate_render_runtime(edit_decisions: dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate that edit_decisions has a recognized render_runtime.

    Returns:
        (True, None) if valid.
        (False, error_message) if missing or unknown.
    """
    if edit_decisions is None:
        return False, "edit_decisions required"

    runtime = (edit_decisions.get("render_runtime") or "").strip().lower()
    if not runtime:
        return False, (
            "render_runtime is not set in edit_decisions. Per governance, "
            "it MUST be locked at proposal stage (proposal_packet."
            "production_plan.render_runtime) and carried forward through "
            "edit_decisions.render_runtime. Valid values: 'remotion', "
            "'hyperframes', 'ffmpeg'. Re-run the proposal stage with an "
            "explicit runtime choice — do NOT default this field."
        )

    if runtime not in VALID_RUNTIMES:
        return False, (
            f"Unknown render_runtime {runtime!r}. "
            f"Valid values: remotion, hyperframes, ffmpeg. "
            f"render_runtime must be set at proposal stage."
        )

    return True, None


def is_remotion_atelier(edit_decisions: dict[str, Any], render_runtime: str) -> bool:
    """Return True if Remotion atelier (bespoke hand-authored) mode is requested."""
    if render_runtime != "remotion":
        return False
    return (
        edit_decisions.get("composition_mode") == "atelier"
        or edit_decisions.get("renderer_family") == "bespoke"
    )


def check_runtime_availability(
    render_runtime: str,
    ffmpeg_ok: bool,
    remotion_ok: bool,
    hyperframes_ok: bool,
) -> Tuple[bool, Optional[str]]:
    """Check that the selected render_runtime is actually available on this system.

    Returns:
        (True, None) if available.
        (False, blocker_message) if unavailable (enforcing fail-closed rule).
    """
    if render_runtime == "hyperframes" and not hyperframes_ok:
        return False, (
            "HyperFrames runtime is not available on this system. "
            "Governance forbids silent fallback to Remotion or FFmpeg. "
            "Install HyperFrames or re-ask user for runtime approval."
        )
    if render_runtime == "remotion" and not remotion_ok:
        return False, (
            "Remotion runtime is not available on this system (requires Node.js, npx, remotion-composer). "
            "Governance forbids silent fallback to FFmpeg or HyperFrames. "
            "Install Remotion or re-ask user for runtime approval."
        )
    if render_runtime == "ffmpeg" and not ffmpeg_ok:
        return False, (
            "FFmpeg binary is not available on this system."
        )
    return True, None


def detect_runtime_swap(
    proposal_packet: Optional[dict[str, Any]],
    edit_decisions: dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Detect if the render runtime changed between proposal and edit stage.

    Returns:
        (True, swap_warning) if a swap was detected.
        (False, None) if matching or unable to determine.
    """
    edit_runtime = (edit_decisions.get("render_runtime") or "").strip().lower()
    proposal_runtime = None

    if proposal_packet and isinstance(proposal_packet, dict):
        proposal_runtime = (
            proposal_packet.get("production_plan", {}).get("render_runtime")
            or proposal_packet.get("render_runtime")
        )

    if not proposal_runtime:
        proposal_runtime = edit_decisions.get("metadata", {}).get("proposal_render_runtime")

    if proposal_runtime:
        proposal_runtime = str(proposal_runtime).strip().lower()
        if proposal_runtime and edit_runtime and proposal_runtime != edit_runtime:
            return True, (
                f"runtime_swap_detected: proposal approved {proposal_runtime!r} "
                f"but edit_decisions specifies {edit_runtime!r} without recorded approval"
            )

    return False, None
