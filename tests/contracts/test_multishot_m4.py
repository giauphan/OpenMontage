"""M4 multi-shot tests — final mastering and fail-closed completion gate.

TASK 016–018. Covers:
  - build_audio_mux_args: silent / narration / music / SFX / subtitle / bounded
    variants produce sane ffmpeg argv; no-audio path strips audio.
  - validate_final_master: fail-closed — blocks on missing / failed / stale
    shots, wrong resolution/FPS/codec, duration deviation, decode failure.
  - can_transition_to_completed: only FINALIZING + clean validation.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_final import (
    build_audio_mux_args,
    can_transition_to_completed,
    FinalValidation,
    validate_final_master,
)
from lib.media_profiles import get_profile


def _clean_probe(profile=None):
    profile = profile or get_profile("tiktok")
    return {
        "duration_sec": 10.0,
        "width": profile.width,
        "height": profile.height,
        "fps": profile.fps,
        "video_codec": "h264",
        "decode_ok": True,
        "has_audio": True,
        "errors": [],
    }


class TestAudioMux:
    def test_silent_base_no_audio_flags(self):
        argv = build_audio_mux_args("base.mp4", "out.mp4", get_profile("tiktok"))
        assert argv[0] == "ffmpeg"
        assert "base.mp4" in argv
        assert "out.mp4" in argv
        # Audio from base is now mapped via "0:a?" instead of copy directly
        assert "-map" in argv
        assert "0:a?" in argv

    def test_narration_bounded_mux(self):
        argv = build_audio_mux_args(
            "base.mp4", "out.mp4", get_profile("tiktok"), narration="narr.mp3", max_duration_sec=42.5,
        )
        assert "narr.mp3" in argv
        assert "-t" in argv and "42.5" in argv

    def test_multi_audio_uses_amix(self):
        argv = build_audio_mux_args(
            "base.mp4", "out.mp4", get_profile("tiktok"), narration="n.mp3", music="m.mp3",
        )
        joined = " ".join(argv)
        assert "-filter_complex" in argv
        assert "sidechaincompress" in joined

    def test_subtitle_sidecar_not_burned(self):
        argv = build_audio_mux_args("base.mp4", "out.mp4", get_profile("tiktok"), subtitles="sub.srt")
        assert "-c:a" in argv
        assert "-map 1:s" in " ".join(argv)
        assert "-c:s" in argv and "mov_text" in argv
        vf_idx = argv.index("-vf")
        assert "subtitles=" not in argv[vf_idx + 1]

    def test_subtitle_burned_uses_vf(self):
        argv = build_audio_mux_args(
            "base.mp4", "out.mp4", get_profile("tiktok"), subtitles="sub.srt", burn_subtitles=True,
        )
        assert "-c:v" in argv and get_profile("tiktok").codec in argv
        assert "-crf" in argv
        assert "-vf" in argv and any("subtitles=" in a for a in argv)



class TestFinalValidation:
    def _validate(self, probe, **kw):
        profile = get_profile("tiktok")
        defaults = dict(
            shot_count=3,
            target_duration_sec=10.0,
            tolerance_sec=0.5,
            profile=profile,
            planned_shot_ids=["shot_001", "shot_002", "shot_003"],
            present_shot_ids=["shot_001", "shot_002", "shot_003"],
            failed_shot_ids=[],
            stale_shot_ids=[],
        )
        defaults.update(kw)
        return validate_final_master(probe, **defaults), profile

    def test_clean_validation_passes(self):
        v, _ = self._validate(_clean_probe())
        assert v.valid, v.errors
        assert v.checks["shot_count"] == 3

    def test_missing_shot_blocks_completion(self):
        v, _ = self._validate(_clean_probe(), present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("missing" in e for e in v.errors)

    def test_failed_shot_blocks_completion(self):
        v, _ = self._validate(
            _clean_probe(),
            shot_count=2,
            planned_shot_ids=["shot_001", "shot_002"],
            present_shot_ids=["shot_001", "shot_002"],
            failed_shot_ids=["shot_002"],
        )
        assert not v.valid
        assert any("failed shots" in e for e in v.errors)

    def test_stale_shot_blocks_completion(self):
        v, _ = self._validate(
            _clean_probe(),
            shot_count=2,
            planned_shot_ids=["shot_001", "shot_002"],
            present_shot_ids=["shot_001", "shot_002"],
            stale_shot_ids=["shot_001"],
        )
        assert not v.valid
        assert any("stale" in e for e in v.errors)

    def test_duration_deviation_blocks_completion(self):
        probe = _clean_probe()
        probe["duration_sec"] = 15.0
        v, _ = self._validate(probe, shot_count=2, target_duration_sec=5.0,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("duration" in e for e in v.errors)

    def test_wrong_resolution_blocks(self):
        profile = get_profile("tiktok")
        probe = _clean_probe()
        probe["width"] = 720
        probe["height"] = 1280
        v, _ = self._validate(probe, shot_count=2,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("resolution" in e for e in v.errors)

    def test_wrong_fps_blocks(self):
        probe = _clean_probe()
        probe["fps"] = 24.0
        v, _ = self._validate(probe, shot_count=2,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("fps" in e for e in v.errors)

    def test_wrong_codec_blocks(self):
        probe = _clean_probe()
        probe["video_codec"] = "hevc"
        v, _ = self._validate(probe, shot_count=2,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("codec" in e for e in v.errors)

    def test_decode_failure_blocks(self):
        probe = _clean_probe()
        probe["decode_ok"] = False
        v, _ = self._validate(probe, shot_count=2,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("decode" in e for e in v.errors)

    def test_expected_audio_present_passes(self):
        v, _ = self._validate(_clean_probe(), expected_audio=True)
        assert v.valid, v.errors

    def test_missing_expected_audio_blocks_completion(self):
        probe = _clean_probe()
        probe["has_audio"] = False
        v, _ = self._validate(probe, expected_audio=True)
        assert not v.valid
        assert any("expected audio track missing" in e for e in v.errors)

    def test_missing_audio_allowed_when_audio_not_requested(self):
        probe = _clean_probe()
        probe["has_audio"] = False
        v, _ = self._validate(probe)
        assert v.valid, v.errors

    def test_single_shot_blocks(self):
        v, _ = self._validate(_clean_probe(), shot_count=1,
                              planned_shot_ids=["shot_001"],
                              present_shot_ids=["shot_001"],
                              target_duration_sec=5.0)
        assert not v.valid
        assert any("< 2" in e for e in v.errors)

    def test_unreadable_duration_blocks(self):
        probe = _clean_probe()
        probe["duration_sec"] = None
        v, _ = self._validate(probe, shot_count=2,
                              planned_shot_ids=["shot_001", "shot_002"],
                              present_shot_ids=["shot_001", "shot_002"])
        assert not v.valid
        assert any("unreadable" in e for e in v.errors)


class TestCompletionGate:
    def _clean(self, status="FINALIZING"):
        profile = get_profile("tiktok")
        v = validate_final_master(
            _clean_probe(profile), shot_count=3,
            target_duration_sec=10.0, tolerance_sec=0.5,
            profile=profile,
            planned_shot_ids=["shot_001", "shot_002", "shot_003"],
            present_shot_ids=["shot_001", "shot_002", "shot_003"],
            failed_shot_ids=[], stale_shot_ids=[],
        )
        return status, v

    def test_finalizing_with_clean_validation_allows(self):
        status, v = self._clean()
        assert can_transition_to_completed(status, validation=v)

    def test_non_finalizing_status_blocks(self):
        status, v = self._clean(status="RENDERING")
        assert not can_transition_to_completed(status, validation=v)

    def test_failed_validation_blocks_even_in_finalizing(self):
        profile = get_profile("tiktok")
        probe = _clean_probe(profile)
        probe["video_codec"] = "hevc"
        v = validate_final_master(
            probe, shot_count=2, target_duration_sec=10.0, tolerance_sec=0.5,
            profile=profile,
            planned_shot_ids=["shot_001", "shot_002"],
            present_shot_ids=["shot_001", "shot_002"],
            failed_shot_ids=[], stale_shot_ids=[],
        )
        assert not v.valid
        assert not can_transition_to_completed("FINALIZING", validation=v)
