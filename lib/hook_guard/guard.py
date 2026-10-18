"""Deterministic HookGuard structural checks, invariant validation, and guard decisions."""

from __future__ import annotations

from typing import Any, Optional

from lib.hook_guard.canonical_edl import (
    compute_body_edl_fingerprint,
    verify_body_edl_preservation,
)
from lib.hook_guard.config import HookPolicy
from lib.hook_guard.grounding import verify_hook_grounding

RULE_VERSION = "hookguard-1"


def evaluate_hook_guard(
    candidate: Optional[dict[str, Any]],
    policy: HookPolicy,
    baseline_body_edl_sha256: str,
    mutated_edl: Optional[dict[str, Any]] = None,
    render_runtime: str = "remotion",
    source_context: Optional[dict[str, Any]] = None,
    video_duration: float = 60.0,
) -> dict[str, Any]:
    """Execute all deterministic structural and policy checks on a hook candidate.
    
    Returns a schema-compliant `guard_result` dict:
    {
      "status": "PASS" | "REJECTED" | "SKIPPED",
      "rule_version": "hookguard-1",
      "reason_codes": list[str],
      "diagnostics": dict,
    }
    """
    reason_codes: list[str] = []
    diagnostics: dict[str, Any] = {}

    # Check 0: Policy status
    if not policy.enabled or policy.mode == "off":
        return {
            "status": "SKIPPED",
            "rule_version": RULE_VERSION,
            "reason_codes": ["SKIPPED_POLICY_OFF"],
            "diagnostics": {"policy_mode": policy.mode, "enabled": policy.enabled},
        }

    if not candidate:
        return {
            "status": "SKIPPED",
            "rule_version": RULE_VERSION,
            "reason_codes": ["SKIPPED_NO_VIABLE_CANDIDATES"],
            "diagnostics": {"error": "No candidate provided for evaluation"},
        }

    cand_mode = candidate.get("mode", "overlay_text")
    cand_window = candidate.get("window", {})
    start_sec = float(cand_window.get("start_seconds", 0.0))
    end_sec = float(cand_window.get("end_seconds", 0.0))
    hook_duration = max(0.0, end_sec - start_sec)

    # Check 1: Runtime compatibility (No silent runtime swaps)
    supported_runtimes = {
        "remotion": {"overlay_text", "caption_emphasis", "extractive_preroll", "script_opening"},
        "hyperframes": {"overlay_text", "script_opening"},
        "ffmpeg": {"overlay_text", "extractive_preroll"},
    }
    allowed_modes = supported_runtimes.get(render_runtime.lower(), set())
    if cand_mode not in allowed_modes:
        reason_codes.append("SKIPPED_RUNTIME_UNSUPPORTED")
        diagnostics["runtime_support"] = {
            "runtime": render_runtime,
            "requested_mode": cand_mode,
            "supported_modes": list(allowed_modes),
        }
        return {
            "status": "SKIPPED" if policy.mode == "auto" else "REJECTED",
            "rule_version": RULE_VERSION,
            "reason_codes": reason_codes,
            "diagnostics": diagnostics,
        }

    # Check 2: Pre-roll permissions and duration budget
    if cand_mode == "extractive_preroll":
        if not policy.allow_preroll:
            reason_codes.append("REJECTED_PREROLL_DISALLOWED")
            diagnostics["preroll"] = "allow_preroll is False in policy"
        preroll_span = candidate.get("preroll_span", {})
        added_duration = float(preroll_span.get("added_duration_seconds", hook_duration))
        if policy.max_added_duration_seconds is not None and added_duration > policy.max_added_duration_seconds:
            reason_codes.append("REJECTED_DURATION_BUDGET_EXCEEDED")
            diagnostics["duration_budget"] = {
                "added_duration": added_duration,
                "max_allowed": policy.max_added_duration_seconds,
            }
        # Check boundary integrity
        boundary_flags = candidate.get("boundary_flags", {})
        if boundary_flags.get("mid_word_cut"):
            reason_codes.append("REJECTED_MID_WORD_BOUNDARY")
        if boundary_flags.get("mid_sentence_cut"):
            reason_codes.append("REJECTED_MID_SENTENCE_BOUNDARY")
    else:
        # Overlay mode must not add duration
        if start_sec >= video_duration or end_sec > video_duration:
            reason_codes.append("REJECTED_DURATION_BUDGET_EXCEEDED")
            diagnostics["bounds"] = {
                "start_seconds": start_sec,
                "end_seconds": end_sec,
                "video_duration": video_duration,
            }

    # Check 3: Audio / Generated TTS permissions
    has_generated_tts = bool(candidate.get("has_generated_tts", False))
    if has_generated_tts and not policy.allow_generated_tts:
        reason_codes.append("REJECTED_AUDIO_SPEECH_COLLISION")
        diagnostics["audio"] = "generated_tts disallowed by policy"

    # Check 4: Truthfulness and Evidence Grounding
    is_grounded, grounding_reason, ground_diag = verify_hook_grounding(candidate, source_context)
    diagnostics["grounding"] = ground_diag
    if not is_grounded:
        if grounding_reason:
            reason_codes.append(grounding_reason)

    # Check 5: Body EDL Invariant Preservation
    if policy.strict_body_edl and mutated_edl:
        preroll_dur = (
            float(candidate.get("preroll_span", {}).get("added_duration_seconds", hook_duration))
            if cand_mode == "extractive_preroll"
            else 0.0
        )
        ok_edl, edl_err = verify_body_edl_preservation(
            baseline_body_edl_sha256,
            mutated_edl,
            mode=cand_mode,
            preroll_duration=preroll_dur,
        )
        if not ok_edl:
            reason_codes.append("REJECTED_BODY_EDL_MUTATED")
            diagnostics["edl_preservation"] = edl_err

    # Final decision
    if not reason_codes:
        return {
            "status": "PASS",
            "rule_version": RULE_VERSION,
            "reason_codes": ["PASS_CLEAN"],
            "diagnostics": diagnostics,
        }

    return {
        "status": "REJECTED",
        "rule_version": RULE_VERSION,
        "reason_codes": reason_codes,
        "diagnostics": diagnostics,
    }
