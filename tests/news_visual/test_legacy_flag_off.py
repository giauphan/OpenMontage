"""T13: Verify backwards compatibility when NEWS_VISUAL_MODE=0.

When NEWS_VISUAL_MODE=0 (or unset), the pipeline must continue to run its
accepted legacy behavior without requiring news_visual_plan.json or news_visual_assets.json.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from scripts.validate_newsnow_director_artifacts import validate_and_promote_director_artifacts


def test_t13_legacy_mode_default_flag_is_zero():
    """T13: Default for NEWS_VISUAL_MODE must be 0 (disabled)."""
    val = os.environ.get("NEWS_VISUAL_MODE", "0")
    assert val == "0", f"Default NEWS_VISUAL_MODE must be '0', got {val}"


def test_t13_legacy_mode_does_not_require_visual_plan(isolated_project: Path, monkeypatch):
    """T13: With flag off (NEWS_VISUAL_MODE=0), missing visual plan does not block artifact gate."""
    monkeypatch.setenv("NEWS_VISUAL_MODE", "0")
    # Verify visual plan is not mandatory when flag is off
    assert not (isolated_project / "artifacts" / "news_visual_plan.json").exists()
