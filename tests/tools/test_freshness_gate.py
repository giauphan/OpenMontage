import pytest
from pathlib import Path
from unittest.mock import MagicMock
import scripts.validate_render_quality

# Refined tests mapping to actual function signature:
# validate_video(
#     path: Path,
#     narration: Path,
#     ffprobe: str,
#     min_duration: float,
#     tolerance: float,
#     expected_dimensions: tuple[int, int],
#     max_duration: float | None = None,
#     narration_text: Path | None = None,
# )

def test_phan_word_preserved_in_subtitles_and_narration():
    """Ensure the Vietnamese word 'phần' is NOT rewritten/mangled by normalize/prepare."""
    from tools.narration_text import prepare_narration, validate_display_text
    text = "Vì AI đã làm thay phần suy nghĩ."
    assert "phần" in prepare_narration(text)
    assert validate_display_text(text) == []

def test_freshness_gate_rejects_audio_with_mismatched_text_timestamp(tmp_path, monkeypatch):
    """Ensure validate_video checks the source text file mtime and flags stale narration audio."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()
    assets_dir = project_dir / "assets"
    assets_dir.mkdir()

    # Create mock narration text
    narration_text_file = artifacts_dir / "narration_vi_text.txt"
    narration_text_file.write_text("Vì AI đã làm thay phần suy nghĩ.", encoding="utf-8")

    # Create mock narration audio (older than the text file)
    narration_audio = assets_dir / "narration.mp3"
    narration_audio.write_bytes(b"mock audio")

    # Make narration_audio older than narration_text_file explicitly
    import os
    os.utime(narration_audio, (1000, 1000))
    os.utime(narration_text_file, (2000, 2000))

    # Mock ffprobe probe return to avoid executing a subprocess
    mock_probe = MagicMock(return_value={
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"}
        ],
        "format": {"duration": "10.0"}
    })
    monkeypatch.setattr("scripts.validate_render_quality.probe", mock_probe)

    # Render is newer than narration audio
    render_video = renders_dir / "final_full_vi_9x16.mp4"
    render_video.write_bytes(b"mock render data")
    os.utime(render_video, (3000, 3000))

    # By default, without checking narration_text, it might pass normal checks:
    # render_video (3000) > narration_audio (1000).
    # But narration_text (2000) > narration_audio (1000), meaning narration_audio is stale!
    # Therefore, the validation must fail.
    errors = scripts.validate_render_quality.validate_video(
        path=render_video,
        narration=narration_audio,
        ffprobe="ffprobe",
        min_duration=5.0,
        tolerance=3.0,
        expected_dimensions=(1080, 1920),
        narration_text=narration_text_file,
    )

    # Expect error stating narration audio is stale / out of date relative to the narration text
    assert any("audio is stale relative to text" in err.lower() or "narration is stale" in err.lower() for err in errors)


def test_staging_replaces_same_size_stale_audio(tmp_path):
    """Same-size-but-different audio must be re-copied into the workspace."""
    from tools.video.hyperframes_compose import HyperFramesCompose

    workspace = tmp_path / "ws"
    (workspace / "assets").mkdir(parents=True)

    src = tmp_path / "narration.mp3"
    src.write_bytes(b"NEW" + b"\x00" * 61)

    stale = workspace / "assets" / "narration.mp3"
    stale.write_bytes(b"OLD" + b"\x00" * 61)
    assert stale.stat().st_size == src.stat().st_size

    out = HyperFramesCompose()._resolve_audio_refs(
        {"narration": {"segments": [{"asset_id": "a1", "start_seconds": 0, "end_seconds": 5}]}},
        [{"id": "a1", "path": str(src)}],
        workspace,
    )

    assert out["narration"][0]["src"] == str(stale)
    assert stale.read_bytes() == src.read_bytes()


def test_staging_replaces_same_size_stale_cut_source(tmp_path):
    """Cut sources must also be content-compared, not size-compared."""
    from tools.video.hyperframes_compose import HyperFramesCompose

    workspace = tmp_path / "ws"
    (workspace / "assets").mkdir(parents=True)

    src = tmp_path / "hero.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nNEW" + b"0" * 64)

    stale = workspace / "assets" / "hero.png"
    stale.write_bytes(b"\x89PNG\r\n\x1a\nOLD" + b"0" * 64)
    assert stale.stat().st_size == src.stat().st_size

    resolved, copies = HyperFramesCompose()._resolve_and_stage_assets(
        [{"id": "c1", "source": "a1", "in_seconds": 0, "out_seconds": 3}],
        [{"id": "a1", "path": str(src)}],
        workspace,
    )

    assert resolved[0]["source"] == str(stale)
    assert stale.read_bytes() == src.read_bytes()
