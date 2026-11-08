"""Unit tests for independent audio completeness and mix quality validation.

Tests:
1. detect_audio_tail_cutoff catches premature truncation mid-speech.
2. verify_spoken_cta_completeness catches missing spoken CTA tokens and cue overflow.
3. audit_audio_mix_quality detects peak clipping and out-of-range mean volume.
4. audit_project_audio_pipeline integrates cleanly into FixedNicheQAValidator.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import pytest

from lib.audio.audio_qa import (
    detect_audio_tail_cutoff,
    verify_spoken_cta_completeness,
    audit_audio_mix_quality,
    audit_project_audio_pipeline,
    measure_audio_levels,
)


def _generate_synthetic_tone(
    path: Path,
    duration: float = 3.0,
    volume: float = 0.5,
    fade_out_duration: float = 0.5,
) -> None:
    """Generate a clean test audio file with natural decay at tail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fade_start = max(0.0, duration - fade_out_duration)
    # Generates 440Hz sine wave with fade-out decay to silence at the tail
    filter_expr = f"volume={volume},afade=t=out:st={fade_start}:d={fade_out_duration}"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-af", filter_expr,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def _generate_truncated_audio(path: Path, duration: float = 3.0, volume: float = 0.9) -> None:
    """Generate audio that cuts off abruptly mid-wave (hard truncate)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Full volume right up to EOF without fade out
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-af", f"volume={volume}",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def test_measure_audio_levels(tmp_path: Path):
    audio_path = tmp_path / "test_levels.mp3"
    _generate_synthetic_tone(audio_path, duration=2.0, volume=0.5)

    levels = measure_audio_levels(audio_path)
    assert levels["mean_volume"] is not None
    assert levels["max_volume"] is not None
    assert levels["mean_volume"] < -5.0
    assert levels["max_volume"] < -2.0


def test_detect_audio_tail_cutoff_clean_decay(tmp_path: Path):
    audio_path = tmp_path / "clean_decay.mp3"
    # Tone with 0.8s fade out before 3.0s EOF
    _generate_synthetic_tone(audio_path, duration=3.0, volume=0.5, fade_out_duration=0.8)

    is_cutoff, details = detect_audio_tail_cutoff(audio_path, sample_window_s=0.25)
    assert not is_cutoff
    assert details["is_abrupt_cutoff"] is False


def test_detect_audio_tail_cutoff_abrupt_truncation(tmp_path: Path):
    audio_path = tmp_path / "hard_cut.mp3"
    _generate_truncated_audio(audio_path, duration=3.0, volume=0.95)

    is_cutoff, details = detect_audio_tail_cutoff(audio_path, sample_window_s=0.20)
    assert is_cutoff
    assert details["is_abrupt_cutoff"] is True
    assert details["tail_mean_volume"] is not None
    assert details["tail_mean_volume"] > -25.0


def test_verify_spoken_cta_completeness_valid(tmp_path: Path):
    project_dir = tmp_path / "proj_valid"
    (project_dir / "artifacts").mkdir(parents=True)
    (project_dir / "assets").mkdir(parents=True)

    # 1. Script with CTA
    script_data = {
        "sections": [
            {"narration": "How agent memory works."},
            {"narration": "Follow for daily AI agent patterns and star the repo for code."},
        ]
    }
    (project_dir / "artifacts" / "script_en_US.json").write_text(json.dumps(script_data))

    # 2. Audio of 4.0s with clean decay
    audio_path = project_dir / "assets" / "narration.mp3"
    _generate_synthetic_tone(audio_path, duration=4.0, volume=0.5, fade_out_duration=0.6)

    # 3. Captions finishing at 3.5s with CTA keywords
    srt_content = (
        "1\n00:00:00,000 --> 00:00:02,000\nHow agent memory works.\n\n"
        "2\n00:00:02,000 --> 00:00:03,500\nFollow and star the repo for code.\n"
    )
    (project_dir / "artifacts" / "captions.srt").write_text(srt_content)

    ok, errors = verify_spoken_cta_completeness(project_dir)
    assert ok, f"Expected success but got: {errors}"
    assert len(errors) == 0


def test_verify_spoken_cta_completeness_cue_overflow(tmp_path: Path):
    project_dir = tmp_path / "proj_overflow"
    (project_dir / "artifacts").mkdir(parents=True)
    (project_dir / "assets").mkdir(parents=True)

    script_data = {
        "sections": [
            {"narration": "Follow for daily AI agent patterns and star the repo for code."},
        ]
    }
    (project_dir / "artifacts" / "script_en_US.json").write_text(json.dumps(script_data))

    # Audio is only 2.0s
    audio_path = project_dir / "assets" / "narration.mp3"
    _generate_synthetic_tone(audio_path, duration=2.0, volume=0.5, fade_out_duration=0.5)

    # Cue extends to 3.2s (speech was truncated by audio length)
    srt_content = "1\n00:00:00,000 --> 00:00:03,200\nFollow and star the repo.\n"
    (project_dir / "artifacts" / "captions.srt").write_text(srt_content)

    ok, errors = verify_spoken_cta_completeness(project_dir)
    assert not ok
    assert any("exceeding narration audio duration" in e for e in errors)


def test_verify_spoken_cta_completeness_missing_spoken_cta_tokens(tmp_path: Path):
    project_dir = tmp_path / "proj_missing_cta"
    (project_dir / "artifacts").mkdir(parents=True)
    (project_dir / "assets").mkdir(parents=True)

    script_data = {
        "sections": [
            {"narration": "Follow for daily AI agent patterns and star the repo for code."},
        ]
    }
    (project_dir / "artifacts" / "script_en_US.json").write_text(json.dumps(script_data))

    audio_path = project_dir / "assets" / "narration.mp3"
    _generate_synthetic_tone(audio_path, duration=3.0, volume=0.5, fade_out_duration=0.5)

    # Final cues lack CTA tokens ("follow", "star", "subscribe")
    srt_content = "1\n00:00:00,000 --> 00:00:02,200\nThis concludes our architectural overview.\n"
    (project_dir / "artifacts" / "captions.srt").write_text(srt_content)

    ok, errors = verify_spoken_cta_completeness(project_dir)
    assert not ok
    assert any("lack spoken CTA keywords" in e for e in errors)


def test_audit_audio_mix_quality_detects_clipping(tmp_path: Path):
    audio_path = tmp_path / "clipping.mp3"
    # Audio with peak right at 0 dB (full scale digital clipping)
    _generate_truncated_audio(audio_path, duration=2.0, volume=15.0)

    ok, errors = audit_audio_mix_quality(audio_path)
    assert not ok
    assert any("harsh digital clipping detected" in e for e in errors)


def test_audit_project_audio_pipeline_integration(tmp_path: Path):
    project_dir = tmp_path / "proj_pipe"
    (project_dir / "artifacts").mkdir(parents=True)
    (project_dir / "assets").mkdir(parents=True)

    script_data = {
        "sections": [
            {"narration": "Follow for daily AI agent patterns and star the repo for code."},
        ]
    }
    (project_dir / "artifacts" / "script_en_US.json").write_text(json.dumps(script_data))
    audio_path = project_dir / "assets" / "narration.mp3"
    _generate_synthetic_tone(audio_path, duration=3.5, volume=0.5, fade_out_duration=0.5)

    srt_content = "1\n00:00:00,000 --> 00:00:03,000\nFollow daily agent patterns and star repo.\n"
    (project_dir / "artifacts" / "captions.srt").write_text(srt_content)

    findings = audit_project_audio_pipeline(project_dir, strict=True)
    blockers = [f for f in findings if f["severity"] == "blocker"]
    assert len(blockers) == 0
