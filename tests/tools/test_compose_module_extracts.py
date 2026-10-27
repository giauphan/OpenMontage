"""Unit tests for extracted _compose helper modules."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.video._compose.asset_resolution import (
    is_image,
    build_asset_lookup,
    resolve_cuts,
    cuts_to_cinematic_scenes,
)
from tools.video._compose.validation import (
    read_text_file,
    tokenize_text,
    compare_transcript_to_script,
    pre_compose_validation,
    TTS_PUNCTUATION_LEAK_WORDS,
)
from tools.video._compose.runtime_policy import (
    validate_render_runtime,
    is_remotion_atelier,
    check_runtime_availability,
    detect_runtime_swap,
)
from tools.video._compose.ffmpeg_commands import (
    build_atempo,
    parse_probe_fps,
    resolve_subtitle_style,
    build_subtitle_style,
)
from tools.video._compose.atelier import (
    run_atelier_checks,
    stage_atelier_project,
    build_theme_from_playbook,
    ATELIER_STOCK_IMPORT_RE,
)
from tools.video._compose.remotion_runner import (
    get_composition_id,
    needs_remotion,
    stage_remotion_media,
    RENDERER_FAMILY_MAP,
)
from tools.video._compose.ffmpeg_effects import (
    has_audio_stream,
    probe_video_stream_duration,
)
from tools.video._compose.review import (
    run_final_review,
)
from tools.video._hyperframes.template import (
    format_float,
    escape_text,
    escape_attr,
    rel_from_workspace,
    compute_total_duration,
    cut_to_html,
    generate_index_html,
)


class TestAssetResolutionExtract:
    """Test asset resolution pure functions."""

    def test_is_image(self):
        assert is_image("photo.png")
        assert is_image(Path("photo.JPG"))
        assert is_image("banner.webp")
        assert not is_image("clip.mp4")
        assert not is_image("audio.wav")
        assert not is_image("")

    def test_build_asset_lookup(self):
        manifest = {
            "assets": [
                {"id": "a1", "path": "/path/to/a1.png", "type": "image"},
                {"id": "a2", "path": "/path/to/a2.mp4", "type": "video"},
            ]
        }
        lookup = build_asset_lookup(manifest)
        assert len(lookup) == 2
        assert lookup["a1"]["path"] == "/path/to/a1.png"
        assert lookup["a2"]["type"] == "video"
        assert build_asset_lookup(None) == {}
        assert build_asset_lookup({}) == {}

    def test_resolve_cuts(self):
        manifest = {
            "assets": [
                {"id": "asset_hero", "path": "/media/hero.mp4"},
            ]
        }
        cuts = [
            {"id": "c1", "source": "asset_hero", "duration": 3.0},
            {"id": "c2", "source": "/direct/path.mp4", "duration": 2.0},
        ]
        resolved = resolve_cuts(cuts, manifest)
        assert len(resolved) == 2
        assert resolved[0]["source"] == "/media/hero.mp4"
        assert resolved[1]["source"] == "/direct/path.mp4"
        assert resolve_cuts([]) == []

    def test_cuts_to_cinematic_scenes(self):
        cuts = [
            {
                "id": "c1",
                "type": "title",
                "text": "Introduction",
                "in_seconds": 0.0,
                "out_seconds": 2.5,
            },
            {
                "id": "c2",
                "type": "video",
                "source": "/path/clip.mp4",
                "in_seconds": 1.0,
                "out_seconds": 5.0,
                "speed": 2.0,
                "transition_in": "cut",
                "transition_out": "none",
            },
        ]
        scenes = cuts_to_cinematic_scenes(cuts)
        assert len(scenes) == 2

        # Scene 1: title
        assert scenes[0]["kind"] == "title"
        assert scenes[0]["text"] == "Introduction"
        assert scenes[0]["startSeconds"] == 0.0
        assert scenes[0]["durationSeconds"] == 2.5

        # Scene 2: video with speed 2.0 (4.0s / 2.0 = 2.0s duration)
        assert scenes[1]["kind"] == "video"
        assert scenes[1]["src"] == "/path/clip.mp4"
        assert scenes[1]["startSeconds"] == 2.5
        assert scenes[1]["durationSeconds"] == 2.0
        assert scenes[1]["fadeInFrames"] == 0
        assert scenes[1]["fadeOutFrames"] == 0


class TestValidationExtract:
    """Test validation and quality check pure functions."""

    def test_tokenize_text(self):
        tokens = tokenize_text("This is an agent-driven test; 100% reliable.")
        assert "this" in tokens
        assert "is" in tokens
        assert "agent-driven" in tokens
        assert "100" in tokens
        assert "reliable" in tokens

    def test_read_text_file(self, tmp_path):
        assert read_text_file(None) is None
        assert read_text_file("/nonexistent/file.txt") is None

        sample_file = tmp_path / "sample.txt"
        sample_file.write_text("sample content", encoding="utf-8")
        assert read_text_file(sample_file) == "sample content"

    def test_compare_transcript_to_script(self, tmp_path):
        # Missing transcript
        res = compare_transcript_to_script(None, "script text")
        assert not res["transcript_matches_script"]
        assert len(res["issues"]) > 0

        # Perfect match
        transcript_path = tmp_path / "transcript.json"
        transcript_path.write_text(
            json.dumps({"word_timestamps": [{"word": "quick"}, {"word": "fox"}]}),
            encoding="utf-8",
        )
        res = compare_transcript_to_script(transcript_path, "quick fox")
        assert res["transcript_matches_script"]
        assert res["word_accuracy"] == 1.0

        # Punctuation leak
        transcript_leak = tmp_path / "transcript_leak.json"
        transcript_leak.write_text(
            json.dumps({"word_timestamps": [{"word": "hello"}, {"word": "dot"}, {"word": "dot"}]}),
            encoding="utf-8",
        )
        res_leak = compare_transcript_to_script(transcript_leak, "hello")
        assert not res_leak["transcript_matches_script"]
        assert len(res_leak["spurious_punctuation_words"]) == 1
        assert res_leak["spurious_punctuation_words"][0]["word"] == "dot"

    def test_pre_compose_validation_blocks_missing_renderer_family(self):
        edit_decisions = {
            "cuts": [{"id": "c1", "source": "dummy.mp4"}],
        }
        res = pre_compose_validation(edit_decisions, edit_decisions["cuts"])
        assert res is not None
        assert not res.success
        assert "renderer_family" in res.error


class TestRuntimePolicyExtract:
    """Test runtime selection and policy enforcement."""

    def test_validate_render_runtime(self):
        valid, err = validate_render_runtime({"render_runtime": "remotion"})
        assert valid and err is None

        valid, err = validate_render_runtime({"render_runtime": "hyperframes"})
        assert valid and err is None

        valid, err = validate_render_runtime({"render_runtime": "ffmpeg"})
        assert valid and err is None

        valid, err = validate_render_runtime({})
        assert not valid
        assert "not set" in err

        valid, err = validate_render_runtime({"render_runtime": "unknown_engine"})
        assert not valid
        assert "Unknown render_runtime" in err

    def test_is_remotion_atelier(self):
        assert is_remotion_atelier({"composition_mode": "atelier"}, "remotion")
        assert is_remotion_atelier({"renderer_family": "bespoke"}, "remotion")
        assert not is_remotion_atelier({"composition_mode": "atelier"}, "hyperframes")
        assert not is_remotion_atelier({}, "remotion")

    def test_check_runtime_availability(self):
        # Missing hyperframes
        ok, err = check_runtime_availability("hyperframes", ffmpeg_ok=True, remotion_ok=True, hyperframes_ok=False)
        assert not ok
        assert "HyperFrames runtime is not available" in err

        # Missing remotion
        ok, err = check_runtime_availability("remotion", ffmpeg_ok=True, remotion_ok=False, hyperframes_ok=True)
        assert not ok
        assert "Remotion runtime is not available" in err

        # All available
        ok, err = check_runtime_availability("remotion", ffmpeg_ok=True, remotion_ok=True, hyperframes_ok=True)
        assert ok and err is None

    def test_detect_runtime_swap(self):
        proposal = {"production_plan": {"render_runtime": "hyperframes"}}
        edits = {"render_runtime": "remotion"}
        swap, msg = detect_runtime_swap(proposal, edits)
        assert swap
        assert "runtime_swap_detected" in msg

        # Matching runtime
        edits_match = {"render_runtime": "hyperframes"}
        swap, msg = detect_runtime_swap(proposal, edits_match)
        assert not swap
        assert msg is None


class TestFFmpegCommandsExtract:
    """Test FFmpeg command and filter helpers."""

    def test_build_atempo(self):
        assert build_atempo(1.0) == "atempo=1.0000"
        chain = build_atempo(250.0)
        assert "atempo=100.0" in chain

    def test_parse_probe_fps(self):
        assert parse_probe_fps("30/1") == 30.0
        assert parse_probe_fps("24000/1001") == 23.98
        assert parse_probe_fps("25") == 25.0
        assert parse_probe_fps("invalid") == 0.0

    def test_resolve_and_build_subtitle_style(self):
        resolved = resolve_subtitle_style(
            explicit_style={"font_size": 32},
            edit_decisions={"subtitles": {"style": {"bold": False}}},
            playbook={"typography": {"body": {"family": "Roboto"}}},
        )
        assert resolved["font"] == "Roboto"
        assert resolved["font_size"] == 32
        assert not resolved["bold"]

        style_str = build_subtitle_style(resolved)
        assert "FontName=Roboto" in style_str
        assert "FontSize=32" in style_str
        assert "Bold=0" in style_str


class TestHyperFramesTemplateExtract:
    """Test HyperFrames HTML generation and formatting pure functions."""

    def test_format_float(self):
        assert format_float(1.0) == "1"
        assert format_float(1.250) == "1.25"
        assert format_float(None) == "0"
        assert format_float(0.0) == "0"
        assert format_float(2.3456) == "2.346"

    def test_escape_text(self):
        assert escape_text("<hello & world>") == "&lt;hello &amp; world&gt;"
        assert escape_text("") == ""
        assert escape_text(None) == ""

    def test_escape_attr(self):
        assert escape_attr('title="test & cool"') == 'title=&quot;test &amp; cool&quot;'
        assert escape_attr("") == ""
        assert escape_attr(None) == ""

    def test_rel_from_workspace(self):
        assert rel_from_workspace("assets/foo.png") == "assets/foo.png"
        assert rel_from_workspace("/home/user/project/assets/bar.png") == "assets/bar.png"
        assert rel_from_workspace("/tmp/other/image.jpg") == "assets/image.jpg"
        assert rel_from_workspace("") == ""

    def test_compute_total_duration(self):
        assert compute_total_duration([{"out_seconds": 2.5}, {"out_seconds": 6.0}]) == 6.0
        assert compute_total_duration([]) == 0.0

    def test_cut_to_html_text_card(self):
        cut = {"type": "text_card", "text": "Intro", "in_seconds": 0.0, "out_seconds": 2.0}
        html, tween = cut_to_html(0, cut, 1920, 1080, {".png"}, {".mp4"})
        assert 'class="clip text-card"' in html
        assert '<h1>Intro</h1>' in html
        assert tween is not None
        assert "tl.from" in tween

    def test_cut_to_html_image_and_video(self):
        # Image
        img_cut = {"source": "assets/photo.png", "in_seconds": 2.0, "out_seconds": 5.0}
        html_img, tween_img = cut_to_html(1, img_cut, 1920, 1080, {".png"}, {".mp4"})
        assert '<img id="cut-1"' in html_img
        assert 'class="clip image-clip"' in html_img
        assert tween_img is not None

        # Video
        vid_cut = {"source": "assets/clip.mp4", "in_seconds": 5.0, "out_seconds": 8.0}
        html_vid, tween_vid = cut_to_html(2, vid_cut, 1920, 1080, {".png"}, {".mp4"})
        assert '<video id="cut-2"' in html_vid
        assert 'class="clip video-clip"' in html_vid
        assert tween_vid is None

    def test_generate_index_html(self):
        cuts = [
            {"type": "text_card", "text": "Hello", "in_seconds": 0.0, "out_seconds": 3.0}
        ]
        audio_refs = {
            "narration": [{"src": "assets/narration.mp3", "start_seconds": 0.0, "end_seconds": 3.0}],
            "music": {"src": "assets/bgm.mp3", "volume": 0.5},
        }
        css_vars = {"--color-bg": "#000", "--color-fg": "#fff"}
        html = generate_index_html(
            cuts=cuts,
            audio_refs=audio_refs,
            width=1920,
            height=1080,
            total_duration=3.0,
            css_vars=css_vars,
            title="Test Video",
            image_extensions={".png"},
            video_extensions={".mp4"},
        )
        assert "<!DOCTYPE html>" in html
        assert "<title>Test Video</title>" in html
        assert "--color-bg: #000;" in html
        assert '<audio id="nar-0"' in html
        assert '<audio id="music"' in html
        assert 'window.__timelines["root"] = tl;' in html


class TestAtelierExtract:
    """Test atelier checks and theme builder pure functions."""

    def test_run_atelier_checks_detects_stock_import(self, tmp_path):
        proj = tmp_path / "my_project"
        proj.mkdir()
        entry = proj / "index.tsx"
        entry.write_text(
            'import { Explainer } from "../../src/Explainer";\nexport const MyComp = () => <div />;',
            encoding="utf-8",
        )
        checks = run_atelier_checks(entry, {"composition_id": "test"})
        assert checks["stock_reuse_detected"]
        assert len(checks["offending_imports"]) == 1
        assert not checks["art_direction_declared"]

    def test_run_atelier_checks_passes_pure_bespoke(self, tmp_path):
        proj = tmp_path / "clean_project"
        proj.mkdir()
        entry = proj / "index.tsx"
        entry.write_text(
            'import { Composition } from "remotion";\nexport const MyComp = () => <div />;',
            encoding="utf-8",
        )
        checks = run_atelier_checks(entry, {"composition_id": "test", "art_direction": "Minimalist Dark"})
        assert not checks["stock_reuse_detected"]
        assert checks["art_direction_declared"]
        assert checks["art_direction"] == "Minimalist Dark"

    def test_build_theme_from_playbook_metadata_fallback(self):
        comp_data = {
            "metadata": {
                "primary_color": "#FF0000",
                "accent_color": "#00FF00",
            }
        }
        theme = build_theme_from_playbook(None, comp_data)
        assert theme is not None
        assert theme["primaryColor"] == "#FF0000"
        assert theme["accentColor"] == "#00FF00"


class TestRemotionRunnerExtract:
    """Test remotion runner resolution and staging functions."""

    def test_get_composition_id(self):
        assert get_composition_id("explainer-data") == "Explainer"
        assert get_composition_id("cinematic-trailer") == "CinematicRenderer"
        assert get_composition_id("presenter") == "TalkingHead"

        with pytest.raises(ValueError):
            get_composition_id("nonexistent_family")

    def test_needs_remotion(self):
        assert not needs_remotion(False, [{"source": "video.mp4"}], {".png"})
        assert not needs_remotion(True, [{"source": "video.mp4"}], {".png"})
        assert needs_remotion(True, [{"source": "slide.png"}], {".png"})
        assert needs_remotion(True, [{"type": "stat_card"}], {".png"})
        assert needs_remotion(True, [{"animation": "fade"}], {".png"})

    def test_stage_remotion_media_in_place(self, tmp_path):
        pub_dir = tmp_path / "public"
        asset_file = tmp_path / "image.png"
        asset_file.write_bytes(b"\x89PNG\r\n\x1a\n")

        payload = {"source": str(asset_file), "nested": {"src": str(asset_file)}}
        count = stage_remotion_media(payload, pub_dir)
        assert count == 1
        assert not payload["source"].startswith("/")
        assert (pub_dir / payload["source"]).exists()


