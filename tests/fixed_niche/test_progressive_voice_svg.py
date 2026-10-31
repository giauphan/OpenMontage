"""Tests for Progressive Voice-Ordered SVG Display in OpenMontage.

Verifies:
1. SVG Pipeline Builder generates structured, sequential step and arrow groups.
2. Step reveals are ordered and timed to match voice narration and ASR word timestamps.
3. Hook block displays when voice introduces AI agent hook; subsequent blocks reveal as voice continues.
4. Embedded keyframes and GSAP tweens guarantee deterministic, seek-safe frame rendering.
5. Backward compatibility: progressive=False produces clean static SVGs without breaking legacy paths.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import pytest

from lib.fixed_niche.svg_pipeline_builder import generate_pipeline_svg, STEP_COUNTS, FAMILY_CONFIGS
from lib.fixed_niche.voice_timing_aligner import (
    compute_step_timings_for_beat,
    generate_progressive_svg_style,
)
from lib.fixed_niche.hyperframes_composer import compose_hyperframes_html


def test_compute_step_timings_sentence_proportions():
    """Verify compute_step_timings_for_beat computes monotonically increasing step timings."""
    narration = (
        "Why do coding agents fail at session boundaries? "
        "The process resets conversational memory to zero. "
        "Then the agent hallucinates unanchored edits. "
        "Finally, continuous integration checks fail before delivery."
    )
    duration = 11.0
    timings = compute_step_timings_for_beat(narration, duration=duration, num_steps=4)

    assert len(timings) == 4
    assert timings[0] == 0.2
    assert timings[0] < timings[1] < timings[2] < timings[3]
    assert timings[-1] <= duration


def test_compute_step_timings_with_word_timestamps():
    """Verify word_timestamps accurately anchor steps to spoken words."""
    word_timestamps = [
        {"word": "Why", "start": 10.2, "end": 10.5},
        {"word": "do", "start": 10.5, "end": 10.7},
        {"word": "agents", "start": 10.8, "end": 11.2},
        {"word": "reset", "start": 13.0, "end": 13.4},
        {"word": "memory", "start": 13.5, "end": 14.0},
        {"word": "hallucinate", "start": 16.0, "end": 16.5},
        {"word": "unanchored", "start": 16.6, "end": 17.1},
        {"word": "edits", "start": 17.2, "end": 17.6},
        {"word": "fail", "start": 19.5, "end": 20.0},
        {"word": "delivery", "start": 20.1, "end": 20.6},
    ]
    duration = 11.0
    beat_start_s = 10.0

    timings = compute_step_timings_for_beat(
        narration="Why do agents reset memory hallucinate unanchored edits fail delivery",
        duration=duration,
        num_steps=4,
        word_timestamps=word_timestamps,
        beat_start_s=beat_start_s,
    )

    assert len(timings) == 4
    # All relative timings must be >= 0.2 and <= duration
    for t in timings:
        assert 0.2 <= t <= duration
    assert timings[0] < timings[1] < timings[2] < timings[3]


def test_generate_progressive_svg_style_keyframes():
    """Verify generate_progressive_svg_style generates valid CSS animations with sequential delays."""
    step_timings = [0.2, 3.0, 6.0, 8.5]
    css = generate_progressive_svg_style(step_timings)

    assert "@keyframes flowStepAppear" in css
    assert "@keyframes flowArrowDraw" in css
    assert ".flow-step {" in css
    assert ".flow-arrow {" in css
    assert "#flow-step-1 { animation-delay: 0.20s; }" in css
    assert "#flow-step-2 { animation-delay: 3.00s; }" in css
    assert "#flow-arrow-1 {" in css
    assert "#flow-step-3 { animation-delay: 6.00s; }" in css
    assert "#flow-step-4 { animation-delay: 8.50s; }" in css


def test_hook_beat_displays_in_voice_order():
    """Test Beat 1 (AI agent pipeline hook) generates distinct sequential step groups.

    User prompt requirement:
    'voice speaking about flow AI agent hook it display block hook , speaking continue it display next'
    """
    svg = generate_pipeline_svg(
        asset_id="diag_hook_01",
        topic_family="context_memory",
        title="Session Memory Boundary Resilience",
        beat_num=1,
        total_beats=6,
        is_vertical=True,
        progressive=True,
        duration=11.0,
        narration="First the developer assigns a task. Then the session resets. The agent hallucinates unanchored edits, causing pipeline deadlock.",
    )

    # 1. Root elements and semantic groups
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in svg
    assert '<g id="flow-header"' in svg

    # Step 1: Hook / Developer task
    assert '<g id="flow-step-1" class="flow-step" data-step-order="1">' in svg
    assert "STEP 1: DEVELOPER TASK" in svg

    # Connecting Arrow 1
    assert '<g id="flow-arrow-1" class="flow-arrow" data-step-order="2">' in svg

    # Step 2: Failure point (reset)
    assert '<g id="flow-step-2" class="flow-step" data-step-order="3">' in svg
    assert "STEP 2: FAILURE POINT" in svg

    # Connecting Arrow 2
    assert '<g id="flow-arrow-2" class="flow-arrow" data-step-order="4">' in svg

    # Step 3: Agent reasoning
    assert '<g id="flow-step-3" class="flow-step" data-step-order="5">' in svg
    assert "STEP 3: AGENT REASONING" in svg

    # Connecting Arrow 3
    assert '<g id="flow-arrow-3" class="flow-arrow" data-step-order="6">' in svg

    # Step 4: Outcome deadlock
    assert '<g id="flow-step-4" class="flow-step" data-step-order="7">' in svg
    assert "OUTCOME: DELIVERY DEADLOCK" in svg

    # 2. Keyframes embedded for voice timing
    assert "flowStepAppear" in svg
    assert "#flow-step-1" in svg
    assert "#flow-step-2" in svg
    assert "#flow-step-3" in svg
    assert "#flow-step-4" in svg


def test_all_beats_generate_valid_step_hierarchies():
    """Verify beats 1 through 6 each generate properly ordered step structures."""
    for beat_num in range(1, 7):
        svg = generate_pipeline_svg(
            asset_id=f"diag_beat_{beat_num}",
            topic_family="agent_tool_use",
            title="Tool Parameter Schema Gate",
            beat_num=beat_num,
            total_beats=6,
            is_vertical=True,
            progressive=True,
            duration=10.5,
        )
        assert f'<g id="flow-step-1"' in svg
        assert f'<g id="flow-arrow-1"' in svg
        assert f'<g id="flow-step-2"' in svg
        assert "flowStepAppear" in svg


def test_backward_compatibility_static_svg():
    """Verify progressive=False produces clean static SVG without animation delays."""
    svg = generate_pipeline_svg(
        asset_id="diag_legacy_01",
        topic_family="debugging_reliability",
        title="CI Regression Gate",
        beat_num=1,
        total_beats=6,
        is_vertical=True,
        progressive=False,
    )
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in svg
    assert "STEP 1: DEVELOPER TASK" in svg
    # Does not inject style block when progressive is False
    assert "@keyframes flowStepAppear" not in svg


def test_hyperframes_composer_inlines_and_animates_steps(tmp_path: Path):
    """Verify compose_hyperframes_html registers GSAP tweens for progressive flow steps."""
    visuals_dir = tmp_path / "assets" / "visuals"
    visuals_dir.mkdir(parents=True)

    # Generate a progressive SVG in visuals_dir
    svg_content = generate_pipeline_svg(
        asset_id="diag_hook_01",
        topic_family="context_memory",
        title="Memory Compaction Resilience",
        beat_num=1,
        total_beats=6,
        is_vertical=True,
        progressive=True,
        duration=11.0,
    )
    (visuals_dir / "diag_hook_01.svg").write_text(svg_content, encoding="utf-8")

    beats = [
        {
            "beat_id": "b01",
            "start_s": 0.0,
            "end_s": 11.0,
            "asset_id": "diag_hook_01",
            "story_function": "problem_hook",
            "visual_kind": "svg_diagram",
            "narration": "Why do autonomous coding agents forget instructions across sessions?",
        }
    ]

    import os
    # Run with standard HyperFrames stage card composer
    os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "0"
    os.environ["OPENMONTAGE_VISUAL_STYLE"] = "stage_card"
    os.environ["OPENMONTAGE_PROGRESSIVE_SVG"] = "1"
    try:
        html = compose_hyperframes_html(
            title="Memory Compaction Resilience",
            duration=11.0,
            beats=beats,
            visuals_src=visuals_dir,
        )

        assert '<!doctype html>' in html
        assert 'id="scene-b01"' in html
        # Inlined SVG or diagram-viewport present
        assert 'class="diagram-viewport"' in html
        assert 'flow-step-1' in html

        # GSAP timeline tweens registered for progressive steps
        assert 'tl.set("#scene-b01 .flow-step"' in html
        assert 'tl.to("#scene-b01 #flow-header"' in html
        assert 'tl.to("#scene-b01 #flow-step-1"' in html
        assert 'tl.to("#scene-b01 #flow-step-2"' in html
        assert 'tl.to("#scene-b01 #flow-arrow-1"' in html
    finally:
        os.environ.pop("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", None)
        os.environ.pop("OPENMONTAGE_VISUAL_STYLE", None)
        os.environ.pop("OPENMONTAGE_PROGRESSIVE_SVG", None)
