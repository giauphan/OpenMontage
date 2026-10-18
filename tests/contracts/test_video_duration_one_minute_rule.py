"""Contract tests enforcing the one-minute video duration rule (>= 60s).

Prevents regressions where generated videos are low-match (25-30s).
Enforces:
  1. Director prompt templates mandate 60-75s (>= 60s) duration, 180-240 words across 5 scenes.
  2. Synthesized director artifacts produce 68s duration, >= 180 Vietnamese words, 5 scenes, and seek-safe GSAP compositions.
  3. Video generation can render a 68s full video (1080x1920) and 59.5s reels video, passing the QA gate with --full-min-duration 60.0.
  4. Short videos (< 30s or < 60s) are rejected when the one-minute minimum duration rule is enforced.
  5. Reels renders exceeding 60.0s are rejected by the YouTube Shorts / Reels cap.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import scripts.validate_newsnow_director_artifacts as director_helper
import scripts.validate_render_quality as render_validator
from tools.narration_text import check_vietnamese_prose, validate_vietnamese_narration

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="ffmpeg and ffprobe must be available for video duration contract tests",
)


def _encode_test_video(path: Path, duration: float, dimensions: str = "1080x1920", color: str = "blue", freq: int = 440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c={color}:size={dimensions}:duration={duration}:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def _encode_narration_audio(path: Path, duration: float, freq: int = 440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
        "-ar", "44100", "-ac", "2",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def test_prompt_templates_mandate_one_minute_and_180_words():
    """Verify director generate and retry prompts explicitly mandate >= 60s and 180-240 words."""
    prompts_dir = ROOT / "scripts" / "prompts"
    gen_prompt = (prompts_dir / "director_generate.prompt.md").read_text(encoding="utf-8")
    retry_prompt = (prompts_dir / "director_retry.prompt.md").read_text(encoding="utf-8")

    for prompt in (gen_prompt, retry_prompt):
        assert "60-75" in prompt or "60–75" in prompt, "Prompt must mandate 60-75s duration"
        assert "180" in prompt and "240" in prompt, "Prompt must mandate 180-240 spoken words"
        assert "intro" in prompt and "context" in prompt and "details" in prompt and "impact" in prompt and "conclusion" in prompt, (
            "Prompt must mandate 5 scene structures"
        )


def test_synthesized_director_artifacts_enforce_one_minute_rule(tmp_path: Path):
    """Verify artifact synthesis produces >= 60s duration, >= 180 Vietnamese words, 5 scenes, and seek-safe compositions."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    brief = {
        "topic": "Đột phá trí tuệ nhân tạo mới",
        "key_points": [
            "Công nghệ mô hình ngôn ngữ lớn phát triển mạnh mẽ",
            "Ứng dụng rộng rãi trong y tế giáo dục và sản xuất",
            "Đảm bảo an toàn thông tin và đạo đức trong phát triển AI",
        ],
    }
    (artifacts / "research_brief.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")

    promoted = director_helper.validate_and_promote_director_artifacts(tmp_path, require_compositions=True)
    assert promoted is True, "Promotion and synthesis must succeed"

    # Check script
    script_path = artifacts / "script_vi.json"
    assert script_path.is_file()
    script = json.loads(script_path.read_text(encoding="utf-8"))

    total_duration = script.get("total_duration_seconds", 0.0)
    assert total_duration >= 60.0, f"Expected total_duration_seconds >= 60.0, got {total_duration}"
    assert total_duration == 68.0

    sections = script.get("sections", [])
    assert len(sections) == 5, f"Expected 5 narrative scenes, got {len(sections)}"

    expected_ids = ["intro", "context", "details", "impact", "conclusion"]
    assert [s["id"] for s in sections] == expected_ids

    # Continuous timestamps
    prev_end = 0.0
    total_words = 0
    for s in sections:
        assert s["start_seconds"] == prev_end
        assert s["end_seconds"] > s["start_seconds"]
        prev_end = s["end_seconds"]

        text = s["text"]
        words = text.split()
        total_words += len(words)

        # Validate Vietnamese language purity
        prose_errs = check_vietnamese_prose(text)
        assert prose_errs == [], f"Section {s['id']} failed Vietnamese check: {prose_errs}"

    assert total_words >= 180, f"Expected >= 180 Vietnamese words, got {total_words}"

    # Check hyperframes full composition (68s)
    full_html = (tmp_path / "hyperframes" / "index.html").read_text(encoding="utf-8")
    assert 'data-duration="68.0"' in full_html
    for scene_id in expected_ids:
        assert f'id="{scene_id}"' in full_html
    assert "window.__timelines['main'] = tl;" in full_html

    # Check hyperframes reels composition (59.5s <= 60s)
    reels_html = (tmp_path / "hyperframes_reels" / "index.html").read_text(encoding="utf-8")
    assert 'data-duration="59.5"' in reels_html
    assert "window.__timelines['main'] = tl;" in reels_html

    # Check seek safety
    seek_errors = director_helper.validate_composition_seek_safety(tmp_path)
    assert seek_errors == [], f"Compositions must be seek-safe: {seek_errors}"


def test_one_minute_video_render_and_reels_pass_quality_gate(tmp_path: Path):
    """Verify video generation renders valid >= 60s full video and <= 60s reels, passing quality validation."""
    project = tmp_path / "project"
    project.mkdir()
    artifacts = project / "artifacts"
    artifacts.mkdir()
    assets = project / "assets"
    assets.mkdir()
    renders = project / "renders"
    renders.mkdir()

    # 1. Narration text
    text_file = artifacts / "narration_vi_text.txt"
    text_file.write_text(
        "Chào mừng quý vị đến với bản tin công nghệ hôm nay. Chúng ta cùng tìm hiểu những bước đột phá mới.",
        encoding="utf-8",
    )
    time.sleep(0.05)

    # 2. Narration audio files (fresh relative to text)
    full_narration = assets / "narration.mp3"
    reels_narration = assets / "narration_reels.mp3"
    _encode_narration_audio(full_narration, duration=68.0)
    _encode_narration_audio(reels_narration, duration=59.5)
    time.sleep(0.05)

    # 3. Rendered MP4 videos (fresh relative to narration)
    full_render = renders / "final_full_vi_9x16.mp4"
    reels_render = renders / "final_reels_vi_9x16.mp4"
    _encode_test_video(full_render, duration=68.0)
    _encode_test_video(reels_render, duration=59.5)

    # Validate individual full video (min_duration=60.0 enforced)
    full_errors = render_validator.validate_video(
        full_render,
        full_narration,
        FFPROBE,
        FFMPEG,
        min_duration=60.0,
        tolerance=3.0,
        expected_dimensions=(1080, 1920),
    )
    assert full_errors == [], f"Full 68s video must pass quality validation: {full_errors}"

    # Validate individual reels video (max_duration=60.0 enforced)
    reels_errors = render_validator.validate_video(
        reels_render,
        reels_narration,
        FFPROBE,
        FFMPEG,
        min_duration=5.0,
        tolerance=3.0,
        expected_dimensions=(1080, 1920),
        max_duration=60.0,
    )
    assert reels_errors == [], f"Reels 59.5s video must pass quality validation: {reels_errors}"

    # Validate full project through CLI entrypoint with --full-min-duration 60.0 --reels-max-duration 60.0
    orig_argv = sys.argv
    sys.argv = [
        "validate_render_quality.py",
        str(project),
        "--ffprobe", FFPROBE,
        "--ffmpeg", FFMPEG,
        "--full-min-duration", "60.0",
        "--reels-max-duration", "60.0",
        "--tolerance", "3.0",
    ]
    try:
        ret = render_validator.main()
        assert ret == 0, "validate_render_quality.main() must pass for 68s full + 59.5s reels"
    finally:
        sys.argv = orig_argv


def test_short_video_rejected_by_one_minute_rule(tmp_path: Path):
    """Verify that a low-match short video (e.g. 28s) fails validation when min-duration is 60s."""
    project = tmp_path / "short_project"
    project.mkdir()
    artifacts = project / "artifacts"
    artifacts.mkdir()
    assets = project / "assets"
    assets.mkdir()
    renders = project / "renders"
    renders.mkdir()

    short_narration = assets / "narration.mp3"
    _encode_narration_audio(short_narration, duration=28.0)
    time.sleep(0.05)

    short_render = renders / "final_full_vi_9x16.mp4"
    _encode_test_video(short_render, duration=28.0)

    # When min_duration is 60.0, the 28s video MUST be rejected
    errors = render_validator.validate_video(
        short_render,
        short_narration,
        FFPROBE,
        FFMPEG,
        min_duration=60.0,
        tolerance=3.0,
        expected_dimensions=(1080, 1920),
    )
    assert any("is not greater than 60.00s" in e for e in errors), (
        f"Expected duration error rejecting 28s video, got: {errors}"
    )


def test_reels_video_exceeding_sixty_seconds_rejected(tmp_path: Path):
    """Verify that a reels video exceeding 60.0s is rejected by the Shorts/Reels cap."""
    project = tmp_path / "long_reels_project"
    project.mkdir()
    assets = project / "assets"
    assets.mkdir()
    renders = project / "renders"
    renders.mkdir()

    long_narration = assets / "narration_reels.mp3"
    _encode_narration_audio(long_narration, duration=65.0)
    time.sleep(0.05)

    long_render = renders / "final_reels_vi_9x16.mp4"
    _encode_test_video(long_render, duration=65.0)

    errors = render_validator.validate_video(
        long_render,
        long_narration,
        FFPROBE,
        FFMPEG,
        min_duration=5.0,
        tolerance=3.0,
        expected_dimensions=(1080, 1920),
        max_duration=60.0,
    )
    assert any("exceeds 60.00s" in e for e in errors), (
        f"Expected max duration error for 65s reels video, got: {errors}"
    )
