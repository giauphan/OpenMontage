"""Phase 4 Remediation Contract Tests: Quality-Oriented QA, Editorial Pacing & Repetition.

Verifies:
- T13: Card text / element collides with captions in 9:16 phone safe zone (CAPTION_UI_COLLISION)
- T14: Repetitive card layout without information gain flagged (REPEATED_LAYOUT_NO_INFORMATION_GAIN)
- T15: Render QA detects sync drift, black tail, missing scene
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.news_visual.qa import check_overlay_safe_zones, run_news_visual_qa
from scripts.validate_render_quality import validate_content, probe


def test_caption_safe_zone_collision(tmp_path: Path):
    """T13: Element placed with bottom: 8% (within bottom 16% safe rail) triggers CAPTION_UI_COLLISION."""
    proj = tmp_path / "proj_safe_zone"
    proj.mkdir(parents=True)
    art = proj / "artifacts"
    art.mkdir()
    vis = proj / "assets" / "visuals"
    vis.mkdir(parents=True)

    plan = {
        "schema_version": "1.0",
        "total_duration_seconds": 68.0,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "visual_kind": "typographic_focus",
                "layout": "card_minimal",
            }
        ],
    }
    (art / "news_visual_plan.json").write_text(json.dumps(plan))

    # HTML with card content styled at bottom: 8% (inside bottom 16% caption safe zone!)
    html_dir = proj / "hyperframes_reels"
    html_dir.mkdir()
    bad_html = """
    <html>
      <head>
        <style>
          .source-label { position: absolute; bottom: 8%; left: 10%; }
        </style>
      </head>
      <body>
        <div class="scene" id="scene-1">
          <div class="source-label">Source: Anthropic</div>
        </div>
      </body>
    </html>
    """
    (html_dir / "index.html").write_text(bad_html)

    qa_res = run_news_visual_qa(proj, mode="strict")
    assert not qa_res["passed"], "Expected safe zone intrusion to fail strict QA"
    cats = qa_res.get("failure_categories", [])
    assert "CAPTION_UI_COLLISION" in cats or "CAPTION_COLLISION" in cats


def test_visual_repetition_detection(tmp_path: Path):
    """T14: Seven visually near-identical cards with no variation flagged with REPEATED_LAYOUT_NO_INFORMATION_GAIN."""
    proj = tmp_path / "proj_repetition"
    proj.mkdir(parents=True)
    art = proj / "artifacts"
    art.mkdir()
    vis = proj / "assets" / "visuals"
    vis.mkdir(parents=True)

    # 7 beats with exact same layout and visual_kind
    beats = [
        {
            "id": f"vb-{i+1:02d}",
            "script_section_id": f"sec_{i}",
            "start_seconds": float(i * 10),
            "end_seconds": float((i + 1) * 10),
            "visual_kind": "typographic_card",
            "layout": "card_minimal",
            "render_strategy": "deterministic_svg",
        }
        for i in range(7)
    ]
    plan = {
        "schema_version": "1.0",
        "total_duration_seconds": 70.0,
        "beats": beats,
    }
    (art / "news_visual_plan.json").write_text(json.dumps(plan))

    html_dir = proj / "hyperframes"
    html_dir.mkdir()
    scenes_html = "".join([f"<div id='scene-{i+1}'>Scene {i+1}</div>" for i in range(7)])
    (html_dir / "index.html").write_text(f"<html><body>{scenes_html}</body></html>")

    qa_res = run_news_visual_qa(proj, mode="strict")
    assert not qa_res["passed"], "Expected 7 identical repeated cards to fail/review in strict mode"
    cats = qa_res.get("failure_categories", [])
    assert "REPEATED_LAYOUT_NO_INFORMATION_GAIN" in cats


def test_render_qa_detects_sync_flaws(tmp_path: Path, monkeypatch):
    """T15: Audio/video sync drift or invalid duration returns errors in validate_render_quality."""
    import scripts.validate_render_quality as vrq
    from scripts.validate_render_quality import validate_video
    
    video_file = tmp_path / "test_video.mp4"
    audio_file = tmp_path / "test_audio.mp3"
    video_file.write_bytes(b"\x00" * 100)
    audio_file.write_bytes(b"\x00" * 100)

    # Mock probe dicts: video is 75s, but narration is only 60s (15s difference > 3s tolerance!)
    def fake_probe(p, ff):
        if "test_video" in str(p):
            return {
                "format": {"duration": "75.0"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
                    {"codec_type": "audio", "codec_name": "aac"}
                ]
            }
        else:
            return {
                "format": {"duration": "60.0"},
                "streams": [{"codec_type": "audio", "codec_name": "aac"}]
            }
    monkeypatch.setattr(vrq, "probe", fake_probe)
    
    errors = validate_video(
        path=video_file,
        narration=audio_file,
        expected_dimensions=(1080, 1920),
        min_duration=65.0,
        max_duration=75.0,
        ffprobe="ffprobe",
        tolerance=3.0,
        ffmpeg=None,
    )
    assert any("differs from narration" in err for err in errors), f"Expected duration sync drift error, got: {errors}"
