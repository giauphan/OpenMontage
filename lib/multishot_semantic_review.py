"""Semantic review helpers for multi-shot acceptance gates."""

from __future__ import annotations

from typing import Any

REQUIRED_SEMANTIC_CHECKS = (
    "character_identity",
    "scene_matches_shot",
    "motion_matches_prompt",
    "continuity_matches_previous",
    "end_state_matches_plan",
    "no_unsafe_imitation",
)


def validate_semantic_review(review: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("semantic_review must be an object")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("semantic_review reviewer must be a non-empty string")
    checks = review.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("semantic_review checks must be an object")
    missing = [key for key in REQUIRED_SEMANTIC_CHECKS if key not in checks]
    if missing:
        raise ValueError(f"semantic_review missing checks: {missing}")
    failed = [key for key in REQUIRED_SEMANTIC_CHECKS if checks[key] is not True]
    if failed:
        raise ValueError(f"semantic_review failed checks: {failed}")
    return {
        "reviewer": reviewer.strip(),
        "checks": {key: bool(checks[key]) for key in REQUIRED_SEMANTIC_CHECKS},
        "notes": str(review.get("notes", "")),
    }
