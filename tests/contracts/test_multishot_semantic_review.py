"""Semantic review gate tests for multi-shot acceptance."""

from __future__ import annotations

import pytest

from lib.multishot_semantic_review import REQUIRED_SEMANTIC_CHECKS, validate_semantic_review


def _review(**overrides):
    checks = {key: True for key in REQUIRED_SEMANTIC_CHECKS}
    checks.update(overrides.pop("checks", {}))
    return {"reviewer": "human", "checks": checks, "notes": "ok", **overrides}


def test_semantic_review_accepts_complete_positive_checklist():
    validated = validate_semantic_review(_review())
    assert validated["reviewer"] == "human"
    assert all(validated["checks"].values())


def test_semantic_review_rejects_failed_continuity_check():
    with pytest.raises(ValueError, match="continuity_matches_previous"):
        validate_semantic_review(_review(checks={"continuity_matches_previous": False}))


def test_semantic_review_rejects_missing_check():
    review = _review()
    review["checks"].pop("motion_matches_prompt")
    with pytest.raises(ValueError, match="motion_matches_prompt"):
        validate_semantic_review(review)
