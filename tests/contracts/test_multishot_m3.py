"""M3 multi-shot media tests — ffprobe, validation, normalization, concat.

TASK 012–015.

The pure-logic tests (build_concat_plan, duration_discrepancy, normalize_clip
dry_run) always run. FFmpeg-backed tests are skipped when the binaries are
absent on the host (media release gates still require execution somewhere).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

from lib.multishot_media import (
    build_concat_plan,
    probe_clip,
    normalize_clip,
    ordered_concat,
    validate_shot_clip,
    duration_discrepancy,
    write_concat_list,
    ConcatEntry,
    MediaError,
)
from lib.media_profiles import get_profile
from lib.multishot_schemas import MultishotValidationError


def _make_clip(path: Path, *, width: int, height: int, fps: int,
               codec: str = "libx264") -> Path:
    """Generate a 1s testsrc clip with the given dimensions / rate / codec."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         f"-i", f"testsrc=duration=1:size={width}x{height}:rate={fps}",
         "-c:v", codec, "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


def _plan(shot_ids: list[str]) -> dict:
    return {
        "version": "1.0",
        "shots": [
            {"id": sid, "order": i + 1, "duration_sec": 5,
             "start_state": {"character": "x", "environment": "y"},
             "end_state": {"character": "x", "environment": "y"},
             "action": "act"}
            for i, sid in enumerate(shot_ids)
        ],
    }


class TestBuildConcatPlan:
    def test_ordered_entries_follow_plan_order(self):
        plan = _plan(["shot_001", "shot_002", "shot_003"])
        entries = build_concat_plan(plan, {f"shot_{i:03d}": f"/n/{i:03d}" for i in (1, 2, 3)})
        assert [e.order for e in entries] == [1, 2, 3]
        assert [e.shot_id for e in entries] == ["shot_001", "shot_002", "shot_003"]

    def test_missing_middle_shot_rejected(self):
        plan = _plan(["shot_001", "shot_002", "shot_003"])
        with pytest.raises(MultishotValidationError, match="missing"):
            build_concat_plan(plan, {"shot_001": "/n/1", "shot_003": "/n/3"})

    def test_extra_shot_rejected(self):
        plan = _plan(["shot_001", "shot_002"])
        with pytest.raises(MultishotValidationError, match="extra"):
            build_concat_plan(plan, {"shot_001": "/n/1", "shot_002": "/n/2", "shot_003": "/n/3"})

    def test_duplicate_ids_rejected(self):
        plan = _plan(["shot_001", "shot_001", "shot_002"])
        with pytest.raises(MultishotValidationError, match="duplicate"):
            build_concat_plan(plan, {"shot_001": "/n/1", "shot_002": "/n/2"})

    def test_zero_entries_rejected(self):
        with pytest.raises(MultishotValidationError, match="zero"):
            ordered_concat([], "out.mp4", get_profile("tiktok"))


class TestConcatListFile:
    def test_write_concat_list_contains_files(self, tmp_path):
        entries = [ConcatEntry("shot_001", 1, "/a.mp4"),
                   ConcatEntry("shot_002", 2, "/b.mp4")]
        lp = tmp_path / "concat.txt"
        write_concat_list(entries, lp)
        content = lp.read_text(encoding="utf-8")
        assert "file '/a.mp4'" in content
        assert "file '/b.mp4'" in content


class TestNormalizeDryRun:
    def test_normalize_dry_run_silent_strips_audio(self):
        argv = normalize_clip("in.mp4", "out.mp4", get_profile("tiktok"),
                              audio_policy="silent", dry_run=True)
        assert "-an" in argv
        assert "scale=1080:1920" in " ".join(argv)

    def test_normalize_invalid_audio_policy_rejected(self):
        with pytest.raises(ValueError, match="audio_policy"):
            normalize_clip("in.mp4", "out.mp4", get_profile("tiktok"),
                          audio_policy="bogus", dry_run=True)


class TestDurationDiscrepancy:
    def test_abs_gap(self):
        assert duration_discrepancy(30.0, 29.5) == pytest.approx(0.5)
        assert duration_discrepancy(30.0, 31.0) == pytest.approx(1.0)


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not on this host")
class TestFFmpegMedia:
    def test_probe_clip_validates_generated_clip(self, tmp_path):
        clip = _make_clip(tmp_path / "clip.mp4", width=320, height=240, fps=30)
        probe = probe_clip(clip)
        assert probe["has_video"] is True
        assert probe["width"] == 320
        assert probe["height"] == 240
        assert probe["decode_ok"] is True
        assert probe["errors"] == []

    def test_probe_rejects_missing_file(self, tmp_path):
        probe = probe_clip(tmp_path / "does-not-exist.mp4")
        assert any("not found" in e for e in probe["errors"])

    def test_validate_shot_clip_duration_tolerance(self, tmp_path):
        clip = _make_clip(tmp_path / "clip.mp4", width=320, height=240, fps=30)
        probe = probe_clip(clip)
        errors = validate_shot_clip(probe, planned_duration_sec=5.0, tolerance_sec=0.5)
        assert any("deviates" in e for e in errors)

    def test_normalize_mixed_inputs_to_canonical(self, tmp_path):
        a = _make_clip(tmp_path / "a.mp4", width=320, height=240, fps=25)
        b = _make_clip(tmp_path / "b.mp4", width=640, height=480, fps=30)
        profile = get_profile("tiktok")

        na = tmp_path / "na.mp4"
        nb = tmp_path / "nb.mp4"
        normalize_clip(a, na, profile, audio_policy="silent")
        normalize_clip(b, nb, profile, audio_policy="silent")

        for p in (probe_clip(na), probe_clip(nb)):
            assert p["width"] == profile.width
            assert p["height"] == profile.height
            assert p["video_codec"] == "h264"
            assert p["pixel_format"] == "yuv420p"

    def test_ordered_concat_end_to_end(self, tmp_path):
        a = _make_clip(tmp_path / "a.mp4", width=320, height=240, fps=30)
        b = _make_clip(tmp_path / "b.mp4", width=640, height=480, fps=30)
        profile = get_profile("tiktok")

        na = tmp_path / "na.mp4"
        nb = tmp_path / "nb.mp4"
        normalize_clip(a, na, profile, audio_policy="silent")
        normalize_clip(b, nb, profile, audio_policy="silent")

        plan = _plan(["shot_001", "shot_002"])
        entries = build_concat_plan(plan, {"shot_001": str(na), "shot_002": str(nb)})
        out = tmp_path / "concat.mp4"
        ordered_concat(entries, out, profile)
        assert out.exists()
        probe = probe_clip(out)
        assert probe["width"] == profile.width
        assert probe["decode_ok"] is True
