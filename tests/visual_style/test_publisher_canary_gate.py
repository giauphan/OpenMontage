"""Canary, rollback, and safety gate tests.

Covers AC-003, AC-015, AC-020, AC-021.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from lib.fixed_niche.hyperframes_composer import (
    compose_hyperframes_html,
    render_ffmpeg_composition,
)
from lib.fixed_niche.policy import load_locked_policy


def test_locked_policy_auto_publish_and_quota_disabled():
    """Policy must strictly declare auto_publish=false, never_force_daily_quota=true."""
    policy = load_locked_policy()
    assert policy.production.get("auto_publish") is False, "auto_publish must be disabled by default"
    assert policy.production.get("generate_video_only") is True, "Must be generate_video_only in locked niche"
    assert policy.production.get("never_force_daily_quota") is True, "Quota forcing must be forbidden"


def test_legacy_mode_produces_original_img_composition(monkeypatch):
    """When visual style is 'legacy', compose_hyperframes_html produces legacy <img> tags."""
    monkeypatch.setenv("OPENMONTAGE_VISUAL_STYLE", "legacy")
    monkeypatch.setenv("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0")

    beats = [
        {"beat_id": "B01", "start_s": 0.0, "end_s": 10.0, "asset_id": "beat_01", "story_function": "intro"}
    ]
    html_output = compose_hyperframes_html("Legacy Test", 72.0, beats)
    assert '<img src="assets/visuals/beat_01.svg"' in html_output
    assert "technical-diagram-svg" not in html_output


def test_new_style_produces_inline_svg_dom(monkeypatch):
    """When visual style is 'animated_agent_diagram_v1', compose_hyperframes_html produces inline SVG."""
    monkeypatch.setenv("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    monkeypatch.setenv("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1")

    beats = [
        {"beat_id": "B01", "start_s": 0.0, "end_s": 10.0, "asset_id": "beat_01", "story_function": "intro"}
    ]
    html_output = compose_hyperframes_html("New Style Test", 72.0, beats)
    assert '<svg id="technical-diagram-svg"' in html_output
    assert "window.__timelines['main'] = tl;" in html_output


def test_ffmpeg_fallback_fails_closed_when_new_style_enabled(tmp_path: Path, monkeypatch):
    """FFmpeg static slideshow fallback must raise RuntimeError when animated diagram style is active."""
    monkeypatch.setenv("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    monkeypatch.setenv("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1")

    out_mp4 = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError, match="Static slideshow fallback via FFmpeg is strictly forbidden"):
        render_ffmpeg_composition(tmp_path, out_mp4, 72.0)
