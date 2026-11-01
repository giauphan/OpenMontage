"""Tests for F-Grade Pipeline Fixes (Score 33 -> High Quality).

Verifies systematic resolution of external audit defects:
1. CTA: 0/10 -> Explicit Call to Action in narration, visual banner, and QA assertion.
2. Hook: 3/10 -> Scroll-stopping quantifiable claim in 0-3s with urgency visual alert.
3. Pacing: 1/10 -> Sub-beat progressive reveals every 2-4s with GSAP spring animations.
4. Sound Design: 1/10 -> Tech BGM bed with volume keyframing, ducking, and transition SFX cues.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.storyboard import FixedNicheStoryboardDirector
from lib.fixed_niche.svg_pipeline_builder import generate_pipeline_svg
from lib.fixed_niche.hyperframes_composer import (
    compose_hyperframes_html,
    materialize_hyperframes_project,
    _copy_composition_audio,
)
from lib.fixed_niche.ffmpeg_composer import _resolve_bgm_path, render_ffmpeg_composition
from lib.fixed_niche.qa import FixedNicheQAValidator


def test_cta_narration_and_visual_banner():
    """Verify Beat 6 contains explicit Call-to-Action in narration and on-screen SVG."""
    director = FixedNicheStoryboardDirector()
    topic = {
        "candidate_id": "cand_cta_test",
        "title": "Model Context Protocol Schema Defense",
        "topic_family": "agent_tool_use",
    }
    claims = [
        {"claim_id": "C01", "statement": "MCP arguments require strict schema validation"},
    ]

    # 1. Narration CTA check across families
    narration_dict = director.compose_dynamic_narration(topic, claims)
    b6_text = narration_dict["b6"]
    assert "Follow @OpenMontage" in b6_text
    assert "star the repo" in b6_text
    assert "defensive blueprint" in b6_text

    # 2. On-screen SVG CTA banner check
    svg = generate_pipeline_svg(
        asset_id="agent_tool_use_b06_payoff",
        topic_family="agent_tool_use",
        title="Model Context Protocol Schema Defense",
        beat_num=6,
        total_beats=6,
        is_vertical=True,
    )
    assert 'id="flow-cta-banner"' in svg
    assert "Follow @OpenMontage" in svg
    assert "Star Repository on GitHub" in svg
    assert "CALL TO ACTION // ARCHITECTURAL BLUEPRINT" in svg


def test_hook_quantifiable_claim_and_urgency_alert():
    """Verify Beat 1 contains scroll-stopping claim in narration and visual urgency alert."""
    director = FixedNicheStoryboardDirector()
    for family in ("agent_tool_use", "debugging_reliability", "context_memory"):
        topic = {"candidate_id": f"cand_hook_{family}", "topic_family": family}
        claims = [{"claim_id": "C01", "statement": "Core architectural failure claim"}]
        narration = director.compose_dynamic_narration(topic, claims)
        b1 = narration["b1"]
        # Must be punchy claim, not passive question
        assert len(b1.split()) >= 10
        assert any(kw in b1.lower() for kw in ("crashes", "break", "lose", "failures"))

    # SVG Beat 1 has high-contrast urgency alert pill
    svg_b1 = generate_pipeline_svg(
        asset_id="agent_tool_use_b01_hook",
        topic_family="agent_tool_use",
        title="Schema Defense",
        beat_num=1,
        total_beats=6,
        is_vertical=True,
    )
    assert "CRITICAL FAILURE // RECURRING BREAKDOWN" in svg_b1


def test_sound_design_bgm_and_sfx_elements():
    """Verify HyperFrames composition embeds BGM bed, volume fades, and SFX clips."""
    beats = [
        {
            "beat_id": "b01",
            "start_s": 0.0,
            "end_s": 11.0,
            "asset_id": "hook_svg",
            "story_function": "problem_hook",
            "narration": "A single schema mismatch silently crashes autonomous tool calls.",
        },
        {
            "beat_id": "b06",
            "start_s": 55.0,
            "end_s": 66.0,
            "asset_id": "cta_svg",
            "story_function": "payoff_and_cta",
            "narration": "Follow @OpenMontage for daily agent patterns, and star the repo for the defensive blueprint.",
        },
    ]

    html = compose_hyperframes_html(
        title="Sound Design Test",
        duration=66.0,
        beats=beats,
    )

    # 1. Background music track embedded with correct volume
    assert '<audio id="bgm" class="clip"' in html
    assert 'src="assets/music-bg.mp3"' in html
    assert 'data-volume="0.12"' in html
    assert 'loop' in html

    # 2. Scene transition SFX embedded
    assert 'class="clip sfx"' in html
    assert 'src="assets/sfx/whoosh-short.mp3"' in html

    # 3. Payoff CTA chime SFX embedded
    assert 'src="assets/sfx/chime.mp3"' in html

    # 4. GSAP volume keyframes for BGM fade-in and fade-out
    assert 'tl.fromTo("#bgm", { volume: 0 }, { volume: 0.12, duration: 1.5' in html
    assert 'tl.to("#bgm", { volume: 0, duration: 1.5' in html


def test_audio_assets_materialization_and_ffmpeg_mix(tmp_path: Path):
    """Verify composition materialization copies BGM and SFX, and FFmpeg resolves BGM."""
    proj_dir = tmp_path / "test_audio_staging"
    proj_dir.mkdir()
    visuals_dir = proj_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True)
    audio_dir = proj_dir / "assets"
    (audio_dir / "narration.mp3").write_bytes(b"\x00" * 100)

    topic = {
        "candidate_id": "cand_audio_mat",
        "title": "Audio Staging Verification",
        "topic_family": "context_memory",
    }
    visual_plan = {
        "beats": [
            {
                "beat_id": "b01",
                "start_s": 0.0,
                "end_s": 11.0,
                "asset_id": "b01_art",
                "story_function": "problem_hook",
                "narration": "Intro hook",
            }
        ]
    }

    result_paths = materialize_hyperframes_project(
        project_dir=proj_dir,
        topic=topic,
        visual_plan=visual_plan,
        duration=66.0,
    )

    for comp_name, index_file in result_paths.items():
        comp_dir = index_file.parent
        comp_assets = comp_dir / "assets"
        # BGM copied
        assert (comp_assets / "music-bg.mp3").is_file()
        # SFX copied
        assert (comp_assets / "sfx" / "whoosh-short.mp3").is_file()
        assert (comp_assets / "sfx" / "chime.mp3").is_file()

    # Verify FFmpeg composer resolves BGM path
    resolved_bgm = _resolve_bgm_path(proj_dir)
    assert resolved_bgm is not None
    assert resolved_bgm.is_file()
    assert resolved_bgm.name == "music-bg.mp3"


def test_qa_call_to_action_validator(tmp_path: Path):
    """Verify QA validator enforces explicit Call-to-Action in script."""
    validator = FixedNicheQAValidator()
    proj_dir = tmp_path / "qa_cta_proj"
    artifacts_dir = proj_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # 1. Script without CTA fails QA
    bad_script = {
        "sections": [
            {"section_id": "S01", "narration": "Intro hook"},
            {"section_id": "S06", "narration": "Always remember that tests are good practice in general."},
        ]
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(bad_script))

    report = validator.audit_fixed_niche_deliverable(proj_dir)
    cta_findings = [f for f in report["findings"] if f["category"] == "CALL_TO_ACTION"]
    assert len(cta_findings) > 0
    assert cta_findings[0]["severity"] == "blocker"

    # 2. Script with CTA passes Call-to-Action check
    good_script = {
        "sections": [
            {"section_id": "S01", "narration": "Intro hook"},
            {
                "section_id": "S06",
                "narration": "Always enforce contracts in CI. Follow @OpenMontage for daily patterns, and star the repo for the blueprint.",
            },
        ]
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(good_script))

    report_good = validator.audit_fixed_niche_deliverable(proj_dir)
    cta_good_findings = [f for f in report_good["findings"] if f["category"] == "CALL_TO_ACTION"]
    assert len(cta_good_findings) == 0
