"""Recovery execution and real-media tests for H3/R4."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

# tiny custom MediaProfile to keep tests fast
from lib.media_profiles import MediaProfile, AspectRatio
TINY_PROFILE = MediaProfile(name="test", width=320, height=240, aspect_ratio=AspectRatio.STANDARD_4_3, fps=30, codec="libx264", audio_codec="aac", crf=28)

from lib.multishot_media import (
    build_concat_plan, normalize_clip, ordered_concat, ConcatEntry, probe_clip
)
from lib.multishot_final import master_final_video

def _make_audio(path: Path, freq: int = 440, duration_sec: float = 1.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         f"-i", f"sine=frequency={freq}:duration={duration_sec}",
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True,
    )
    return path

def _make_clip(path: Path, *, width: int, height: int, fps: int, color: str = "black", duration_sec: float = 1.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         f"-i", f"color=c={color}:s={width}x{height}:r={fps}:d={duration_sec}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path

@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg required")
class TestRealisticFFmpegCommands:
    def test_audio_ducking_with_sidechaincompress(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=5.0)
        n = _make_audio(tmp_path / "n.mp3", freq=600, duration_sec=5.0)
        m = _make_audio(tmp_path / "m.mp3", freq=440, duration_sec=5.0)
        out = tmp_path / "out.mp4"

        args = master_final_video(str(base), str(out), TINY_PROFILE,
                           narration=str(n), music=str(m), dry_run=True)

        joined = " ".join(args)
        assert "-filter_complex" in args
        assert "sidechaincompress=threshold=-20.0dB" in joined

    def test_burning_subtitles_reencodes(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30)
        out = tmp_path / "out.mp4"
        subs = tmp_path / "subs.srt"
        subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello")

        args = master_final_video(str(base), str(out), TINY_PROFILE,
                           subtitles=str(subs), burn_subtitles=True, dry_run=True)

        joined = " ".join(args)
        assert "-c:v libx264" in joined
        assert "-vf" in args and "subtitles=" in joined

    def test_missing_middle_concat_handled_by_plan(self, tmp_path):
        plan = {
            "version": "1.0",
            "shots": [
                {"id": "shot_001", "order": 1},
                {"id": "shot_002", "order": 2},
                {"id": "shot_003", "order": 3},
            ]
        }
        with pytest.raises(Exception, match="missing shots: \\['shot_002'\\]"):
            build_concat_plan(plan, {
                "shot_001": "n/1",
                "shot_003": "n/3"
            })

    def test_execution_master_final_video_silent_base(self, tmp_path):
        # Actual execution test for silent base
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=2.0)
        out = tmp_path / "out.mp4"

        args = master_final_video(str(base), str(out), TINY_PROFILE, dry_run=False)

        assert out.exists()
        probe = probe_clip(out)
        assert probe["duration_sec"] == pytest.approx(2.0, abs=0.1)

    def test_execution_master_final_video_with_audio_ducking(self, tmp_path):
        # Actual execution test with audio tracks
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=3.0)
        n = _make_audio(tmp_path / "n.mp3", freq=600, duration_sec=3.0)
        m = _make_audio(tmp_path / "m.mp3", freq=440, duration_sec=3.0)
        out = tmp_path / "out.mp4"

        args = master_final_video(str(base), str(out), TINY_PROFILE,
                           narration=str(n), music=str(m), dry_run=False)

        assert out.exists()
        probe = probe_clip(out)
        assert probe["has_audio"]
        assert probe["duration_sec"] == pytest.approx(3.0, abs=0.1)

    def test_execution_master_final_video_single_narration(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=2.0)
        n = _make_audio(tmp_path / "n.mp3", freq=600, duration_sec=2.0)
        out = tmp_path / "out.mp4"

        master_final_video(str(base), str(out), TINY_PROFILE, narration=str(n), dry_run=False)

        assert out.exists()
        probe = probe_clip(out)
        assert probe["has_audio"]
        assert probe["duration_sec"] == pytest.approx(2.0, abs=0.1)

    def test_execution_master_final_video_mux_subtitle(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=2.0)
        subs = tmp_path / "subs.srt"
        subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello")
        out = tmp_path / "out.mp4"

        master_final_video(str(base), str(out), TINY_PROFILE, subtitles=str(subs), burn_subtitles=False, dry_run=False)

        assert out.exists()
        # ffprobe doesn't necessarily output subtitle stream in basic probe_clip unless we check all streams
        # Let's do a fast ffprobe for the subtitle codec mov_text
        output = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "s:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(out)],
            text=True, timeout=5.0
        ).strip()
        assert output == "mov_text"

    def _get_pixel_rgb(self, video_path: str, timestamp: float) -> tuple[int, int, int]:
        raw = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", video_path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            timeout=5.0
        )
        # return the middle pixel of 320x240 image
        idx = (120 * 320 + 160) * 3
        return raw[idx], raw[idx+1], raw[idx+2]

    def test_execution_master_final_video_burn_subtitle(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=2.0, color="black")
        subs = tmp_path / "subs.srt"
        # large white text
        subs.write_text("1\n00:00:00,000 --> 00:00:02,000\n<font color=\"white\">HELLOTEXTFRAME</font>")
        out_burned = tmp_path / "out_burned.mp4"
        out_noburn = tmp_path / "out_noburn.mp4"

        master_final_video(str(base), str(out_burned), TINY_PROFILE, subtitles=str(subs), burn_subtitles=True, dry_run=False)
        master_final_video(str(base), str(out_noburn), TINY_PROFILE, dry_run=False)

        # A non-burned black clip should have roughly black pixels
        black_rgb = self._get_pixel_rgb(str(out_noburn), 1.0)
        assert sum(black_rgb) < 50

        # We can't guarantee exactly the text pixel, so we sum all pixels
        raw_noburn = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(out_noburn), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            timeout=5.0
        )
        raw_burned = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(out_burned), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            timeout=5.0
        )
        assert sum(raw_burned) > sum(raw_noburn) + 1000

    def test_execution_master_final_video_source_audio_preservation(self, tmp_path):
        # Base clip with audio
        base = tmp_path / "base_with_audio.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             f"-i", f"color=c=black:s={TINY_PROFILE.width}x{TINY_PROFILE.height}:r={TINY_PROFILE.fps}:d=2.0",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base)],
            check=True, capture_output=True, timeout=10.0
        )
        out = tmp_path / "out.mp4"

        master_final_video(str(base), str(out), TINY_PROFILE, dry_run=False)

        assert out.exists()
        probe = probe_clip(out)
        assert probe["has_audio"]

    def test_execution_master_final_video_three_audio_tracks_with_fades(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=3.0)
        n = _make_audio(tmp_path / "n.mp3", freq=600, duration_sec=5.0) # slightly longer audio
        m = _make_audio(tmp_path / "m.mp3", freq=440, duration_sec=5.0)
        sfx = _make_audio(tmp_path / "sfx.mp3", freq=880, duration_sec=5.0)
        out = tmp_path / "out.mp4"

        # Audio should be clamped to 3.0 sec
        master_final_video(str(base), str(out), TINY_PROFILE,
                           narration=str(n), music=str(m), sfx=str(sfx),
                           audio_fade_in_sec=1.0, audio_fade_out_sec=1.0,
                           dry_run=False)

        probe = probe_clip(out)
        assert probe["has_audio"]
        assert probe["duration_sec"] == pytest.approx(3.0, abs=0.1)

    def test_boundary_color_concat(self, tmp_path):
        # Real concat boundary color ordering test
        a = _make_clip(tmp_path / "a.mp4", width=320, height=240, fps=30, color="red", duration_sec=1.0)
        b = _make_clip(tmp_path / "b.mp4", width=320, height=240, fps=30, color="blue", duration_sec=1.0)

        plan = {
            "version": "1.0",
            "shots": [
                {"id": "a", "order": 1},
                {"id": "b", "order": 2},
            ]
        }

        entries = build_concat_plan(plan, {"a": str(a), "b": str(b)})
        out = tmp_path / "concat.mp4"
        ordered_concat(entries, out, TINY_PROFILE)

        assert out.exists()
        probe = probe_clip(out)
        assert probe["duration_sec"] == pytest.approx(2.0, abs=0.1)

        rgb_0_5 = self._get_pixel_rgb(str(out), 0.5)
        rgb_1_5 = self._get_pixel_rgb(str(out), 1.5)

        # Red frame
        assert rgb_0_5[0] > 100
        assert rgb_0_5[1] < 50
        assert rgb_0_5[2] < 50

        # Blue frame
        assert rgb_1_5[0] < 50
        assert rgb_1_5[1] < 50
        assert rgb_1_5[2] > 100

    def test_invalid_corrupt_input_preserves_existing_output(self, tmp_path):
        base = _make_clip(tmp_path / "base.mp4", width=320, height=240, fps=30, duration_sec=1.0)
        out = tmp_path / "out.mp4"
        out.write_text("existing output")
        corrupt_audio = tmp_path / "n.mp3"
        corrupt_audio.write_text("not an audio file")

        with pytest.raises(Exception):
            master_final_video(str(base), str(out), TINY_PROFILE,
                               narration=str(corrupt_audio), dry_run=False)

        assert out.read_text() == "existing output"
        assert not Path(str(out) + ".tmp.mp4").exists()

