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


def test_hyperframes_composer_inlines_and_animates_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    # Run with standard HyperFrames stage card composer using monkeypatch
    monkeypatch.setenv("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0")
    monkeypatch.setenv("OPENMONTAGE_VISUAL_STYLE", "stage_card")
    monkeypatch.setenv("OPENMONTAGE_PROGRESSIVE_SVG", "1")

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

    # Date and stage number badges removed from ontop
    assert 'class="stage-header"' not in html
    assert 'class="date-badge"' not in html
    assert 'class="stage-badge"' not in html

    # GSAP timeline tweens registered for progressive steps
    assert 'tl.set("#scene-b01 .flow-step"' in html
    assert 'tl.to("#scene-b01 #flow-header"' in html
    assert '#scene-b01 #flow-step-1' in html
    assert '#scene-b01 #flow-step-2' in html
    assert '#scene-b01 #flow-arrow-1' in html


def test_materialize_hyperframes_project_folder_hygiene_no_svg_files(tmp_path: Path):
    """Ensure materialized composition folders contain NO static SVG images.

    Videos handle SVG diagrams dynamically via inline DOM in index.html,
    so assets/visuals within hyperframes/ and hyperframes_reels/ must not
    contain static .svg image files.
    """
    from lib.fixed_niche.hyperframes_composer import materialize_hyperframes_project

    proj_dir = tmp_path / "test_video_hygiene"
    proj_dir.mkdir()
    visuals_src = proj_dir / "assets" / "visuals"
    visuals_src.mkdir(parents=True)

    # Pre-populate static SVG files in project assets/visuals
    for beat_num in range(1, 7):
        (visuals_src / f"agent_tool_use_b{beat_num:02d}.svg").write_text("<svg></svg>", encoding="utf-8")

    topic = {
        "candidate_id": "cand_hygiene",
        "title": "What actually happens when an AI agent calls an MCP tool",
        "topic_family": "agent_tool_use",
    }
    visual_plan = {
        "beats": [
            {
                "beat_id": f"b{i:02d}",
                "start_s": float(i - 1) * 11.0,
                "end_s": float(i) * 11.0,
                "asset_id": f"agent_tool_use_b{i:02d}",
                "topic_family": "agent_tool_use",
                "story_function": "stage",
                "visual_kind": "svg_diagram",
                "narration": f"Stage {i} MCP execution step",
            }
            for i in range(1, 7)
        ]
    }

    result_paths = materialize_hyperframes_project(
        project_dir=proj_dir,
        topic=topic,
        visual_plan=visual_plan,
        duration=66.0,
    )

    for comp_name, index_file in result_paths.items():
        assert index_file.is_file()
        comp_dir = index_file.parent
        comp_visuals = comp_dir / "assets" / "visuals"

        # 1. No .svg files copied or left in composition assets/visuals
        if comp_visuals.is_dir():
            svg_files = list(comp_visuals.glob("*.svg"))
            assert len(svg_files) == 0, f"Found unexpected SVG files in {comp_visuals}: {svg_files}"

        # 2. Composition index.html contains inlined SVG DOM with progressive flow steps
        html = index_file.read_text(encoding="utf-8")
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in html
        assert 'id="flow-step-1"' in html
        assert 'id="flow-arrow-1"' in html
        assert 'id="flow-step-2"' in html

        # 3. Progressive GSAP tweens reveal items in voice order
        assert '#scene-b01 #flow-step-1' in html
        assert '#scene-b01 #flow-arrow-1' in html
        assert '#scene-b01 #flow-step-2' in html

        # 4. No <img> fallback pointing to static .svg files
        assert '<img src="assets/visuals/' not in html or not any(
            f'assets/visuals/agent_tool_use_b{i:02d}.svg' in html for i in range(1, 7)
        )


def test_dynamic_in_memory_svg_when_no_svg_on_disk(tmp_path: Path):
    """Ensure compose_hyperframes_html inlines dynamic SVG DOM even with no SVG files on disk."""
    beats = [
        {
            "beat_id": "b01",
            "start_s": 0.0,
            "end_s": 11.0,
            "asset_id": "agent_tool_use_b01_hook",
            "topic_family": "agent_tool_use",
            "story_function": "problem_hook",
            "visual_kind": "svg_diagram",
            "narration": "First, the developer assigns a tool calling instruction. Then the schema validation fails.",
        }
    ]

    html = compose_hyperframes_html(
        title="What actually happens when an AI agent calls an MCP tool",
        duration=11.0,
        beats=beats,
        visuals_src=None,  # No files on disk
    )

    # Inlined SVG DOM must be generated in-memory rather than falling back to broken <img>
    assert '<!doctype html>' in html
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in html
    assert 'id="flow-step-1"' in html
    assert 'id="flow-arrow-1"' in html
    assert 'id="flow-step-2"' in html
    assert '<img src="assets/visuals/' not in html
    assert '#scene-b01 #flow-step-1' in html


def test_svg_beat_text_wrapping_no_overlap():
    """Verify render_wrapped_text wraps delimiters and long sentences into multi-line tspans."""
    from lib.fixed_niche.svg_beats import render_wrapped_text

    # Delimiter '//' wrapping
    delim_svg = render_wrapped_text("⚡ SCHEMA BREACH // Argument Reject", 145, 432, max_chars=24)
    assert "<tspan" in delim_svg
    assert "⚡ SCHEMA BREACH" in delim_svg
    assert "Argument Reject" in delim_svg

    # Long sentence wrapping
    long_desc = "Invoke tool with dynamic parameters and structured output"
    wrapped_svg = render_wrapped_text(long_desc, 145, 246, max_chars=32)
    assert "<tspan" in wrapped_svg
    assert "Invoke tool with dynamic" in wrapped_svg


def test_multi_scene_progressive_reveals_and_unique_ids(tmp_path: Path):
    """Verify scenes 2 through 6 have distinct scoped IDs and progressive GSAP tweens."""
    beats = [
        {
            "beat_id": f"b{i:02d}",
            "start_s": float(i - 1) * 11.5,
            "end_s": float(i) * 11.5,
            "asset_id": f"beat_{i}",
            "topic_family": "agent_tool_use",
            "story_function": "stage",
            "visual_kind": "svg_diagram",
            "narration": f"Stage {i} MCP execution step with progressive details and voice synchronization",
        }
        for i in range(1, 7)
    ]

    html = compose_hyperframes_html(
        title="Circuit Breakers in Multi-Agent Execution",
        duration=69.0,
        beats=beats,
        visuals_src=None,
    )

    # Document-level CSS keeps all progressive steps hidden at start
    assert ".flow-step {" in html or ".flow-step {" in html.replace("  ", " ")
    assert "opacity: 0;" in html

    # Scene 1 uses standard step IDs
    assert '#scene-b01 #flow-step-1' in html
    assert '#scene-b01 #flow-step-2' in html

    # Scenes 2-6 use scoped prefixes to prevent ID collision and ensure sequential reveal
    assert '#scene-b02 #b02-flow-step-1' in html
    assert '#scene-b02 #b02-flow-step-2' in html
    assert '#scene-b03 #b03-flow-step-1' in html
    assert '#scene-b04 #b04-flow-step-1' in html
    assert '#scene-b05 #b05-flow-step-1' in html
    assert '#scene-b06 #b06-flow-step-1' in html

    # Timing: Scene 2 step 2 must animate later than step 1
    # Check that tween for b02-flow-step-2 has a higher timestamp than b02-flow-step-1
    m1 = re.search(r'tl\.fromTo\("#scene-b02 #b02-flow-step-1"[^;]+,\s*([0-9.]+)\);', html)
    m2 = re.search(r'tl\.fromTo\("#scene-b02 #b02-flow-step-2"[^;]+,\s*([0-9.]+)\);', html)
    assert m1 and m2, "Scene 2 step tweens not found in GSAP timeline"
    t1, t2 = float(m1.group(1)), float(m2.group(1))
    assert t2 > t1 + 1.0, f"Scene 2 step 2 time ({t2}) must be at least 1s after step 1 ({t1})"


def test_sound_design_varied_sfx_and_cta_timing():
    """Verify varied SFX (buzz, pass-ping, click, pop, chime) and CTA banner timing bounds."""
    beats = [
        {
            "beat_id": f"b{i:02d}",
            "start_s": float(i - 1) * 11.5,
            "end_s": float(i) * 11.5,
            "asset_id": f"beat_{i}",
            "topic_family": "agent_tool_use",
            "story_function": "stage",
            "visual_kind": "svg_diagram",
            "narration": f"Stage {i} MCP execution step with audio synchronization and failure recovery",
        }
        for i in range(1, 7)
    ]

    html = compose_hyperframes_html(
        title="Circuit Breakers Sound Design",
        duration=69.0,
        beats=beats,
        visuals_src=None,
    )

    # Varied retention sound effects embedded
    assert 'src="assets/sfx/buzz.mp3"' in html
    assert 'src="assets/sfx/pass-ping.mp3"' in html
    assert 'src="assets/sfx/chime.mp3"' in html
    assert 'src="assets/sfx/whoosh-short.mp3"' in html

    # CTA banner tween scheduled before composition duration (69.0s)
    m_cta = re.search(r'tl\.fromTo\("#scene-b06 #b06-flow-cta-banner"[^;]+,\s*([0-9.]+)\);', html)
    assert m_cta is not None, "b06-flow-cta-banner tween not found"
    cta_t = float(m_cta.group(1))
    assert cta_t < 69.0, f"CTA banner timestamp ({cta_t}) must be before composition duration (69.0)"
    assert cta_t >= 60.0, f"CTA banner timestamp ({cta_t}) must be within Beat 6 window"

    # Step 4 reveal timestamp must be strictly BEFORE CTA banner reveal timestamp,
    # ensuring all sequential pipeline blocks display first, then the CTA banner,
    # with all elements persisting until the end of the video.
    m_step4 = re.search(r'tl\.fromTo\("#scene-b06 #b06-flow-step-4"[^;]+,\s*([0-9.]+)\);', html)
    assert m_step4 is not None, "b06-flow-step-4 tween not found"
    step4_t = float(m_step4.group(1))
    assert step4_t < cta_t, f"Step 4 ({step4_t}s) must reveal BEFORE CTA banner ({cta_t}s)!"
    assert 69.0 - cta_t >= 2.0, f"CTA banner must display for at least 2.0s before video end (actual: {69.0 - cta_t}s)"

    # Verify Beat 3 reveals final step early enough to hold for >= 2.0s before transition
    m_b03_step3 = re.search(r'tl\.fromTo\("#scene-b03 #b03-flow-step-3"[^;]+,\s*([0-9.]+)\);', html)
    assert m_b03_step3 is not None, "b03-flow-step-3 tween not found"
    b03_step3_t = float(m_b03_step3.group(1))
    b03_end = float(beats[2]["end_s"])
    assert (b03_end - b03_step3_t) >= 2.0, (
        f"Beat 3 final step must display for >= 2.0s before scene exit (actual: {b03_end - b03_step3_t:.2f}s)"
    )


def test_all_scenes_end_block_hold_time_contract():
    """Verify all scene flows guarantee 2.0s to 4.0s hold time for the completed diagram state.

    User prompt requirement:
    'frametime 32 - 34 block end it display 2 - 4s it's faster it next screen continue .
    you check voice and image screen it .ensure that the on-screen image and the voice are synchronized'
    'ensure fixed all flow after'
    'doesn't hardcord'
    """
    from lib.fixed_niche.voice_timing_aligner import compute_step_timings_for_beat, compute_cta_timing
    from lib.fixed_niche.svg_pipeline_builder import STEP_COUNTS

    beats = [
        {"duration": 11.66, "narration": "Beat 1 hook text about failure", "num_steps": STEP_COUNTS[1]},
        {"duration": 11.66, "narration": "Beat 2 developer impact cascade", "num_steps": STEP_COUNTS[2]},
        {"duration": 11.66, "narration": "Beat 3 architectural mechanism client breaker tool", "num_steps": STEP_COUNTS[3]},
        {"duration": 11.66, "narration": "Beat 4 verified remedy automatic recovery", "num_steps": STEP_COUNTS[4]},
        {"duration": 11.66, "narration": "Beat 5 local automated verification gate tests pass", "num_steps": STEP_COUNTS[5]},
        {"duration": 11.66, "narration": "Beat 6 end-to-end production pipeline flow summary", "num_steps": STEP_COUNTS[6]},
    ]

    # Verify standard scenes (Beats 1 to 5)
    for idx, beat in enumerate(beats[:5], start=1):
        dur = beat["duration"]
        n_steps = beat["num_steps"]
        timings = compute_step_timings_for_beat(
            narration=beat["narration"],
            duration=dur,
            num_steps=n_steps,
            is_final_beat=False,
        )
        assert len(timings) == n_steps
        assert timings[0] == 0.2
        # Monotonically increasing
        for s in range(len(timings) - 1):
            assert timings[s + 1] > timings[s]

        last_step_t = timings[-1]
        hold_time = dur - last_step_t
        # Hold time must be between 2.0s and 4.0s
        assert 2.0 <= hold_time <= 4.0, (
            f"Beat {idx} hold time ({hold_time:.2f}s) outside guaranteed 2.0s - 4.0s range!"
        )

    # Verify final scene (Beat 6)
    b6 = beats[5]
    b6_timings = compute_step_timings_for_beat(
        narration=b6["narration"],
        duration=b6["duration"],
        num_steps=b6["num_steps"],
        is_final_beat=True,
    )
    assert len(b6_timings) == b6["num_steps"]
    cta_rel = compute_cta_timing(b6["duration"], b6_timings, lead_time=1.0)
    assert cta_rel > b6_timings[-1], "CTA must appear after all steps have revealed!"
    final_hold = b6["duration"] - cta_rel
    assert final_hold >= 3.0, f"Final scene CTA hold time ({final_hold:.2f}s) must be >= 3.0s!"


def test_hook_alert_data_driven_from_config():
    """Verify hook alert badge text is driven from FAMILY_CONFIGS without hardcoded strings."""
    from lib.fixed_niche.svg_pipeline_builder import generate_pipeline_svg, FAMILY_CONFIGS

    for fam_key, cfg in FAMILY_CONFIGS.items():
        assert "hook_alert" in cfg, f"Family '{fam_key}' missing hook_alert in FAMILY_CONFIGS!"
        svg = generate_pipeline_svg(
            asset_id=f"test_{fam_key}",
            topic_family=fam_key,
            title="Test Flow Title",
            beat_num=1,
            total_beats=6,
            is_vertical=True,
        )
        assert cfg["hook_alert"] in svg, f"Generated SVG missing configured hook_alert for '{fam_key}'!"




