"""Extended unit tests for the HyperFrames runtime integration.

Covers decision log validation, transcript comparison checks, workspace
scaffolding, style bridge, schema acceptance, slideshow risk, and
composition validation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.base_tool import ToolResult
from tools.video.hyperframes_compose import HyperFramesCompose
from tools.video.video_compose import VideoCompose
from tests.tools._hyperframes_test_helpers import (
    SAMPLE_CLEAN_TRANSCRIPT,
    SAMPLE_PUNCTUATION_LEAK_TRANSCRIPT,
    build_tiny_mp4,
    make_render_runner,
    valid_runtime_decision,
)


def test_decision_log_accepts_render_runtime_selection_with_both_options():
    """Schema-level: a decision_log with BOTH runtimes in options_considered must validate."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        pytest.skip("jsonschema not installed")

    root = Path(__file__).resolve().parent.parent.parent
    schema = json.loads(
        (root / "schemas" / "artifacts" / "decision_log.schema.json").read_text(encoding="utf-8")
    )

    log = {
        "version": "1.0",
        "project_id": "p-test",
        "decisions": [
            valid_runtime_decision(
                [
                    {
                        "option_id": "remotion",
                        "label": "Remotion",
                        "score": 0.6,
                        "reason": "existing React scene stack fits",
                    },
                    {
                        "option_id": "hyperframes",
                        "label": "HyperFrames",
                        "score": 0.4,
                        "reason": "GSAP motion is natural but caption parity deferred",
                    },
                ]
            )
        ],
    }
    jsonschema.validate(log, schema)


def test_transcript_comparison_catches_literal_punctuation_leak(tmp_path):
    """Regression: transcript_comparison check catches TTS reading literal '...' as 'dot'."""
    script_text = (
        "A computer just did in five minutes what would take every machine on Earth, "
        "running since the Big Bang, ten septillion years to finish. "
        "We may have gotten help from parallel universes."
    )
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(SAMPLE_PUNCTUATION_LEAK_TRANSCRIPT), encoding="utf-8")

    result = VideoCompose._compare_transcript_to_script(transcript_path, script_text)

    assert result["spurious_punctuation_words"]
    leak_counts = {
        entry["word"]: entry["count"]
        for entry in result["spurious_punctuation_words"]
    }
    assert leak_counts.get("dot") == 4, f"Expected 4 'dot' leaks, got {leak_counts}"

    issue_text = " ".join(result["issues"]).lower()
    assert "tts punctuation leak" in issue_text
    assert "not in the script" in issue_text
    assert result["transcript_matches_script"] is False


def test_transcript_comparison_passes_clean_audio(tmp_path):
    """Clean audio with no punctuation leaks must NOT trigger a false positive."""
    script_text = "The quick brown fox jumps over the lazy dog."
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(SAMPLE_CLEAN_TRANSCRIPT), encoding="utf-8")

    result = VideoCompose._compare_transcript_to_script(transcript_path, script_text)
    assert result["spurious_punctuation_words"] == []
    assert result["transcript_matches_script"] is True
    assert result["word_accuracy"] >= 0.9
    assert not any("tts punctuation leak" in i.lower() for i in result["issues"])


def test_transcript_comparison_graceful_when_inputs_missing(tmp_path):
    """When transcript or script is unavailable, the check records skip in issues."""
    result = VideoCompose._compare_transcript_to_script(None, "some script text")
    assert any("not provided" in i for i in result["issues"])

    dummy = tmp_path / "t.json"
    dummy.write_text('{"word_timestamps": []}', encoding="utf-8")
    result = VideoCompose._compare_transcript_to_script(dummy, "")
    assert any("not provided" in i for i in result["issues"])

    result = VideoCompose._compare_transcript_to_script(tmp_path / "nonexistent.json", "script")
    assert any("not provided" in i for i in result["issues"])


def test_run_final_review_includes_transcript_comparison_section(tmp_path):
    """Regression: `transcript_comparison` section must ALWAYS appear in final_review."""
    mp4 = build_tiny_mp4(tmp_path / "out.mp4")

    review = VideoCompose()._run_final_review(
        mp4,
        edit_decisions={
            "version": "1.0",
            "renderer_family": "animation-first",
            "render_runtime": "hyperframes",
            "cuts": [{"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2}],
        },
    )
    assert "transcript_comparison" in review["checks"]
    tc = review["checks"]["transcript_comparison"]
    assert any("not provided" in i for i in tc["issues"])


def test_hyperframes_root_composition_has_data_start_and_duration(tmp_path):
    """Regression: generated root composition must have data-start and data-duration."""
    asset = tmp_path / "hero.png"
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 512)
    workspace = tmp_path / "hyperframes"
    result = HyperFramesCompose().execute(
        {
            "operation": "scaffold_workspace",
            "workspace_path": str(workspace),
            "edit_decisions": {
                "version": "1.0",
                "render_runtime": "hyperframes",
                "renderer_family": "animation-first",
                "cuts": [
                    {
                        "id": "c1",
                        "source": "a1",
                        "in_seconds": 0,
                        "out_seconds": 5,
                        "type": "image",
                    }
                ],
            },
            "asset_manifest": {"assets": [{"id": "a1", "path": str(asset)}]},
        }
    )
    assert result.success, result.error
    html = (workspace / "index.html").read_text(encoding="utf-8")
    assert 'data-composition-id="root"' in html
    assert 'data-start="0"' in html
    m = re.search(r'data-duration="([^"]+)"', html)
    assert m, "root composition missing data-duration"
    assert float(m.group(1)) == pytest.approx(5.0)
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html


def test_video_compose_blocks_hyperframes_when_runtime_unavailable(tmp_path, monkeypatch):
    """Governance: if render_runtime='hyperframes' is locked but runtime is missing, fail closed."""
    monkeypatch.setattr(VideoCompose, "_hyperframes_available", lambda self: False, raising=True)

    result = VideoCompose().execute(
        {
            "operation": "render",
            "edit_decisions": {
                "version": "1.0",
                "cuts": [{"id": "c1", "source": "a1", "in_seconds": 0, "out_seconds": 3}],
                "render_runtime": "hyperframes",
                "renderer_family": "animation-first",
            },
            "asset_manifest": {"assets": [{"id": "a1", "path": "does-not-matter.png"}]},
            "output_path": str(tmp_path / "out.mp4"),
        }
    )
    assert not result.success
    err = (result.error or "").lower()
    assert "hyperframes" in err
    assert "blocker" in err or "not available" in err


def test_video_compose_honors_hyperframes_runtime_before_atelier_mode(tmp_path, monkeypatch):
    """Regression for F-14: composition_mode='atelier' must not force Remotion when hyperframes is locked."""
    monkeypatch.setattr(VideoCompose, "_hyperframes_available", lambda self: False, raising=True)

    result = VideoCompose().execute(
        {
            "operation": "render",
            "edit_decisions": {
                "version": "1.0",
                "cuts": [{"id": "c1", "source": "a1", "in_seconds": 0, "out_seconds": 3}],
                "render_runtime": "hyperframes",
                "composition_mode": "atelier",
                "renderer_family": "animation-first",
            },
            "asset_manifest": {"assets": [{"id": "a1", "path": "does-not-matter.png"}]},
            "output_path": str(tmp_path / "out.mp4"),
        }
    )

    assert not result.success
    err = (result.error or "").lower()
    assert "hyperframes" in err
    assert "not available" in err or "blocker" in err
    assert "remotion entry" not in err


# ------------------------------------------------------------------
# Scaffold / workspace generation (no CLI invocation)
# ------------------------------------------------------------------


def test_scaffold_workspace_generates_html_and_assets(tmp_path: Path):
    asset = tmp_path / "hero.png"
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 1024)

    workspace = tmp_path / "hyperframes"
    edit_decisions: dict[str, Any] = {
        "version": "1.0",
        "renderer_family": "animation-first",
        "render_runtime": "hyperframes",
        "cuts": [
            {"id": "c1", "source": "asset_hero", "in_seconds": 0, "out_seconds": 3, "type": "image"},
            {"id": "c2", "source": "", "in_seconds": 3, "out_seconds": 6, "type": "text_card", "text": "Hello HyperFrames"},
        ],
    }
    asset_manifest = {"assets": [{"id": "asset_hero", "path": str(asset)}]}

    result = HyperFramesCompose().execute(
        {
            "operation": "scaffold_workspace",
            "workspace_path": str(workspace),
            "edit_decisions": edit_decisions,
            "asset_manifest": asset_manifest,
            "playbook": {
                "name": "test-playbook",
                "visual_language": {
                    "color_palette": {
                        "background": "#0B0F1A",
                        "text": "#F5F5F5",
                        "accent": "#F59E0B",
                    }
                },
                "typography": {
                    "heading": {"font": "Inter"},
                    "body": {"font": "Inter"},
                },
            },
        }
    )

    assert result.success, result.error
    index = workspace / "index.html"
    assert index.is_file()
    html = index.read_text(encoding="utf-8")

    assert 'data-composition-id="root"' in html
    assert 'window.__timelines["root"]' in html
    assert 'paused: true' in html
    assert 'class="clip' in html
    assert "gsap" in html.lower()
    assert 'data-start="3"' in html
    assert 'Hello HyperFrames' in html

    staged = workspace / "assets" / "hero.png"
    assert staged.is_file()
    assert "assets/hero.png" in html

    hf_json = workspace / "hyperframes.json"
    assert hf_json.is_file()
    config = json.loads(hf_json.read_text(encoding="utf-8"))
    assert config["paths"]["blocks"] == "compositions"

    design = workspace / "DESIGN.md"
    assert design.is_file()
    design_text = design.read_text(encoding="utf-8")
    assert "#0B0F1A" in design_text or "test-playbook" in design_text


def test_scaffold_rejects_empty_cuts(tmp_path: Path):
    result = HyperFramesCompose().execute(
        {
            "operation": "scaffold_workspace",
            "workspace_path": str(tmp_path / "hyperframes"),
            "edit_decisions": {"version": "1.0", "cuts": []},
            "asset_manifest": {"assets": []},
        }
    )
    assert not result.success
    assert "cuts" in (result.error or "").lower()


# ------------------------------------------------------------------
# Style bridge
# ------------------------------------------------------------------


def test_style_bridge_fallback_has_all_required_vars():
    from lib.hyperframes_style_bridge import style_bridge

    css, design = style_bridge(None, None)
    for key in (
        "--color-bg",
        "--color-fg",
        "--color-accent",
        "--color-primary",
        "--font-heading",
        "--font-body",
        "--ease-primary",
        "--duration-entrance",
    ):
        assert key in css, f"missing CSS var: {key}"
    assert "# DESIGN" in design


def test_style_bridge_picks_up_playbook_palette():
    from lib.hyperframes_style_bridge import style_bridge

    playbook = {
        "name": "neon-test",
        "visual_language": {
            "color_palette": {
                "background": "#000000",
                "text": "#FFFFFF",
                "accent": ["#FF00FF", "#FF66FF"],
                "primary": "#00FFFF",
            }
        },
        "typography": {
            "heading": {"font": "Space Grotesk"},
            "body": {"font": "Inter"},
        },
        "motion": {"pace": "fast"},
    }
    css, design = style_bridge(playbook, None)
    assert css["--color-bg"] == "#000000"
    assert css["--color-accent"] == "#FF00FF"
    assert css["--color-primary"] == "#00FFFF"
    assert css["--font-heading"] == "Space Grotesk"
    assert css["--duration-entrance"].startswith("0.")
    assert "neon-test" in design


def test_style_bridge_edit_decision_override_wins():
    from lib.hyperframes_style_bridge import style_bridge

    playbook = {
        "visual_language": {"color_palette": {"background": "#111", "text": "#eee"}},
    }
    edit = {"metadata": {"background_color": "#fff", "accent_color": "#09f"}}
    css, _ = style_bridge(playbook, edit)
    assert css["--color-bg"] == "#fff"
    assert css["--color-accent"] == "#09f"


# ------------------------------------------------------------------
# Schema acceptance for render_runtime
# ------------------------------------------------------------------


def test_proposal_packet_schema_accepts_render_runtime():
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "artifacts" / "proposal_packet.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    props = schema["properties"]["production_plan"]["properties"]
    assert "render_runtime" in props
    assert "renderer_family" in props
    assert props["render_runtime"]["enum"] == ["remotion", "hyperframes", "ffmpeg"]


def test_schemas_accept_voice_performance_contract():
    root = Path(__file__).resolve().parent.parent.parent

    script_schema = json.loads(
        (root / "schemas" / "artifacts" / "script.schema.json").read_text(encoding="utf-8")
    )
    assert "voice_performance" in script_schema["properties"]
    section_props = script_schema["properties"]["sections"]["items"]["properties"]
    assert "delivery_cues" in section_props
    assert "provider_text" in section_props["delivery_cues"]["properties"]

    proposal_schema = json.loads(
        (root / "schemas" / "artifacts" / "proposal_packet.schema.json").read_text(encoding="utf-8")
    )
    voice_selection = proposal_schema["properties"]["production_plan"]["properties"][
        "voice_selection"
    ]["properties"]
    assert "delivery_style" in voice_selection
    assert "pacing_policy" in voice_selection
    assert "sample_approval_required" in voice_selection

    asset_schema = json.loads(
        (root / "schemas" / "artifacts" / "asset_manifest.schema.json").read_text(encoding="utf-8")
    )
    asset_props = asset_schema["properties"]["assets"]["items"]["properties"]
    assert "voice_performance" in asset_props
    assert "provider_settings" in asset_props["voice_performance"]["properties"]


def test_tts_provider_contracts_match_supported_fields():
    from tools.audio.elevenlabs_tts import ElevenLabsTTS
    from tools.audio.google_tts import GoogleTTS
    from tools.audio.openai_tts import OpenAITTS

    google_props = GoogleTTS.input_schema["properties"]
    assert google_props["input_type"]["enum"] == ["text", "ssml"]
    assert google_props["speaking_rate"]["maximum"] == 2.0
    assert google_props["pitch"]["minimum"] == -20.0
    assert google_props["pitch"]["maximum"] == 20.0

    openai_props = OpenAITTS.input_schema["properties"]
    assert "response_format" in openai_props
    assert {"mp3", "opus", "aac", "flac", "wav", "pcm"}.issubset(
        set(openai_props["response_format"]["enum"])
    )
    assert OpenAITTS._supports_instructions("gpt-4o-mini-tts")
    assert not OpenAITTS._supports_instructions("tts-1")
    assert not OpenAITTS._supports_instructions("tts-1-hd")

    eleven_props = ElevenLabsTTS.input_schema["properties"]
    assert {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"}.issubset(
        set(eleven_props)
    )
    assert eleven_props["speed"]["minimum"] == 0.7
    assert eleven_props["speed"]["maximum"] == 1.2


def test_edit_decisions_schema_accepts_render_runtime():
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "artifacts" / "edit_decisions.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "render_runtime" in schema["properties"]
    assert schema["properties"]["render_runtime"]["enum"] == ["remotion", "hyperframes", "ffmpeg"]


def test_final_review_tracks_runtime_and_swap():
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "artifacts" / "final_review.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    pp = schema["properties"]["checks"]["properties"]["promise_preservation"]["properties"]
    assert "render_runtime_used" in pp
    assert "runtime_swap_detected" in pp


def test_decision_log_has_render_runtime_category():
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "artifacts" / "decision_log.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    category_enum = schema["properties"]["decisions"]["items"]["properties"]["category"]["enum"]
    assert "render_runtime_selection" in category_enum


# ------------------------------------------------------------------
# Slideshow risk & Composition validator
# ------------------------------------------------------------------


def test_slideshow_risk_accepts_render_runtime():
    from lib.slideshow_risk import score_slideshow_risk

    scenes = [
        {
            "type": "image",
            "description": "Opening shot of city",
            "shot_language": {"shot_size": "wide"},
            "shot_intent": "establish",
        },
        {
            "type": "text_card",
            "description": "Title overlay",
            "shot_language": {"shot_size": "medium"},
            "shot_intent": "announce",
        },
    ]
    out = score_slideshow_risk(scenes, render_runtime="hyperframes")
    assert out["render_runtime"] == "hyperframes"
    assert out["verdict"] in {"strong", "acceptable", "revise", "fail"}


def test_composition_validator_hyperframes_asset_root(tmp_path: Path):
    """With render_runtime='hyperframes', validator looks for assets next to index.html."""
    from tools.analysis.composition_validator import CompositionValidator

    workspace = tmp_path / "hyperframes"
    (workspace / "assets").mkdir(parents=True)
    (workspace / "index.html").write_text("<!-- stub -->", encoding="utf-8")
    asset = workspace / "assets" / "hero.png"
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 10)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    comp_json = artifacts_dir / "comp.json"
    comp_json.write_text(
        json.dumps(
            {
                "render_runtime": "hyperframes",
                "cuts": [{"id": "c1", "source": "hero.png", "in_seconds": 0, "out_seconds": 3}],
            }
        ),
        encoding="utf-8",
    )

    result = CompositionValidator().execute({"composition_path": str(comp_json)})
    assert result.success, result.error
    info_lines = " ".join(result.data.get("info", []))
    assert "hyperframes" in info_lines.lower() or "assets" in info_lines.lower()


def test_hyperframes_render_rejects_empty_output(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = HyperFramesCompose()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    monkeypatch.setattr(tool, "_scaffold", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_validate", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_run_hf", make_render_runner(b""))

    result = tool._render(
        {"workspace_path": str(workspace), "output_path": "renders/final.mp4"}
    )
    assert not result.success
    assert "missing or empty" in (result.error or "")


def test_hyperframes_render_rejects_corrupted_output(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = HyperFramesCompose()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool, "_runtime_check", lambda: {"runtime_available": True})
    monkeypatch.setattr(tool, "_scaffold", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_lint", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_validate", lambda inputs: ToolResult(success=True, data={}))
    monkeypatch.setattr(tool, "_run_hf", make_render_runner(b"x" * 2000))
    monkeypatch.setattr("lib.media_integrity.verify_video_integrity", lambda *a, **k: (False, "mock decode failed", {}))

    result = tool._render(
        {"workspace_path": str(workspace), "output_path": "renders/final.mp4"}
    )
    assert not result.success
    assert "failed video integrity verification" in (result.error or "")
