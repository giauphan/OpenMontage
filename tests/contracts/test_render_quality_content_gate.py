"""Content-level QA gates for the render→publish chain.

Metadata-only validation (dimensions, codec, fps, duration) passed videos that
were unwatchable: an all-black 1080x1920 h264 render with a silent AAC track
satisfied every check. These tests pin the decode-level gates in
`scripts/validate_render_quality.py` — silent audio and blank video must fail —
and pin `scripts/check_qa.py` to argument-driven project paths instead of the
hardcoded container paths and candidate IDs it used before.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_render_quality = _load("validate_render_quality")
check_qa = _load("check_qa")

DURATION = 4
DIMENSIONS = "1080x1920"
# The production gate requires >30s renders. Tests pin the *content* checks, so
# they use short clips plus a lowered --min-duration to keep encode/decode cheap.
MIN_DURATION = "2"
TOLERANCE = "1"


def _run(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, check=True)


def _narration(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={DURATION}",
          "-ar", "44100", "-ac", "2", str(path)])


def _render(path: Path, *, blank: bool = False, silent: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    video = (
        f"color=c=black:size={DIMENSIONS}:duration={DURATION}:rate=30"
        if blank
        else f"testsrc=size={DIMENSIONS}:duration={DURATION}:rate=30"
    )
    audio = (
        "anullsrc=r=44100:cl=stereo"
        if silent
        else f"sine=frequency=440:duration={DURATION}"
    )
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio,
          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-shortest", str(path)])


def _project(tmp_path: Path, *, blank: bool = False, silent: bool = False) -> Path:
    project = tmp_path / "project"
    _narration(project / "assets" / "narration.mp3")
    for name in ("final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"):
        _render(project / "renders" / name, blank=blank, silent=silent)
    return project


def _validate(project: Path) -> int:
    argv = [
        "validate_render_quality.py",
        str(project),
        "--ffprobe", shutil.which("ffprobe"),
        "--ffmpeg", shutil.which("ffmpeg"),
        "--min-duration", MIN_DURATION,
        "--tolerance", TOLERANCE,
    ]
    original = sys.argv
    sys.argv = argv
    try:
        return validate_render_quality.main()
    finally:
        sys.argv = original


def test_healthy_render_passes(tmp_path):
    assert _validate(_project(tmp_path)) == 0


def test_silent_audio_fails(tmp_path, capsys):
    assert _validate(_project(tmp_path, silent=True)) == 1
    assert "effectively silent" in capsys.readouterr().err


def test_blank_video_fails(tmp_path, capsys):
    assert _validate(_project(tmp_path, blank=True)) == 1
    assert "is black" in capsys.readouterr().err


def test_dark_blue_blank_video_fails_in_strict_mode(tmp_path, capsys):
    project = tmp_path / "dark_project"
    _narration(project / "assets" / "narration.mp3")
    dark_video = f"color=c=0x0a0e1a:size={DIMENSIONS}:duration={DURATION}:rate=30"
    audio = f"sine=frequency=440:duration={DURATION}"
    for name in ("final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"):
        path = project / "renders" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", dark_video, "-f", "lavfi", "-i", audio,
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30",
              "-c:a", "aac", "-shortest", str(path)])

    argv = [
        "validate_render_quality.py",
        str(project),
        "--ffprobe", shutil.which("ffprobe"),
        "--ffmpeg", shutil.which("ffmpeg"),
        "--min-duration", MIN_DURATION,
        "--tolerance", TOLERANCE,
        "--strict",
    ]
    original = sys.argv
    sys.argv = argv
    try:
        assert validate_render_quality.main() == 1
    finally:
        sys.argv = original
    assert "edge density" in capsys.readouterr().err


def test_production_min_duration_rejects_short_render(tmp_path):
    """The shipped default still enforces the pipeline's >30s contract."""
    project = _project(tmp_path)
    original = sys.argv
    sys.argv = [
        "validate_render_quality.py",
        str(project),
        "--ffprobe", shutil.which("ffprobe"),
        "--ffmpeg", shutil.which("ffmpeg"),
    ]
    try:
        assert validate_render_quality.main() == 1
    finally:
        sys.argv = original


def test_reels_narration_override_is_used(tmp_path):
    """A shorter Reels excerpt is measured against its own narration."""
    project = _project(tmp_path)
    reels_narration = project / "assets" / "narration_reels.mp3"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
          "-ar", "44100", "-ac", "2", str(reels_narration)])

    resolved = validate_render_quality.resolve_narration(
        project, "narration_reels.mp3", "narration.mp3"
    )
    assert resolved == reels_narration

    full = validate_render_quality.resolve_narration(project, "narration.mp3")
    assert full == project / "assets" / "narration.mp3"


def test_missing_ffmpeg_is_reported_not_skipped(tmp_path):
    """Without ffmpeg the content gate must fail closed, never pass silently."""
    project = _project(tmp_path)
    errors = validate_render_quality.validate_content(
        project / "renders" / "final_full_vi_9x16.mp4",
        None,
        float(DURATION),
        has_audio=True,
        has_video=True,
    )
    assert any("cannot verify audio/video content" in error for error in errors)


def test_check_qa_accepts_project_arguments(tmp_path, capsys):
    project = _project(tmp_path)
    original = sys.argv
    sys.argv = ["check_qa.py", str(project), "--ffprobe", shutil.which("ffprobe")]
    try:
        assert check_qa.main() == 0
    finally:
        sys.argv = original
    assert "GATE2=PASS" in capsys.readouterr().out


def test_check_qa_fails_on_missing_reels_render(tmp_path, capsys):
    project = _project(tmp_path)
    (project / "renders" / "final_reels_vi_9x16.mp4").unlink()
    original = sys.argv
    sys.argv = ["check_qa.py", str(project), "--ffprobe", shutil.which("ffprobe")]
    try:
        assert check_qa.main() == 1
    finally:
        sys.argv = original
    assert "GATE2=FAIL" in capsys.readouterr().out


def test_frozen_canvas_fails_in_strict_mode(tmp_path, capsys):
    project = tmp_path / "frozen_project"
    _narration(project / "assets" / "narration.mp3")
    audio = f"sine=frequency=440:duration={DURATION}"
    for name in ("final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"):
        path = project / "renders" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Use loop/still image encoding to generate truly frozen frames
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:size={DIMENSIONS}:duration={DURATION}:rate=30",
              "-f", "lavfi", "-i", audio,
              "-vf", "drawbox=x=100:y=100:w=800:h=400:color=white:t=fill",
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "30",
              "-c:a", "aac", "-shortest", str(path)])

    argv = [
        "validate_render_quality.py",
        str(project),
        "--ffprobe", shutil.which("ffprobe"),
        "--ffmpeg", shutil.which("ffmpeg"),
        "--min-duration", MIN_DURATION,
        "--tolerance", TOLERANCE,
        "--strict",
    ]
    original = sys.argv
    sys.argv = argv
    try:
        assert validate_render_quality.main() == 1
    finally:
        sys.argv = original
    assert "frozen canvas" in capsys.readouterr().err

