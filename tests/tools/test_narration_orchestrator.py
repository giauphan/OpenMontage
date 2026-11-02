"""Unit tests for NarrationOrchestrator helper methods and audio fallback mechanisms."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from lib.audio.narration_orchestrator import (
    NarrationOrchestrator,
    probe_audio_duration,
    safe_write_narration_text,
    _resolve_default_cache_dir,
    _resolve_default_lock_path,
)


def test_probe_audio_duration(tmp_path: Path):
    # Non-existent or empty file
    assert probe_audio_duration(tmp_path / "non_existent.mp3") == -1.0
    empty_f = tmp_path / "empty.mp3"
    empty_f.touch()
    assert probe_audio_duration(empty_f) == -1.0

    # Successful probe
    valid_f = tmp_path / "valid.mp3"
    valid_f.write_bytes(b"DATA")
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout="42.5\n")
        assert probe_audio_duration(valid_f) == 42.5

        # Probe failure exception
        mock_sub.side_effect = RuntimeError("ffprobe crashed")
        assert probe_audio_duration(valid_f) == -1.0


def test_safe_write_narration_text(tmp_path: Path):
    target = tmp_path / "narration.txt"
    # 1. First write -> True
    assert safe_write_narration_text(target, "Hello world") is True
    assert target.read_text(encoding="utf-8") == "Hello world"

    # 2. Duplicate write -> False
    assert safe_write_narration_text(target, "Hello world") is False

    # 3. Changed text -> True
    assert safe_write_narration_text(target, "New text") is True
    assert target.read_text(encoding="utf-8") == "New text"


def test_resolve_cache_and_lock_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENMONTAGE_CACHE_DIR", str(tmp_path / "custom_cache"))
    cache_dir = _resolve_default_cache_dir()
    assert cache_dir == tmp_path / "custom_cache" / "narration"

    monkeypatch.setenv("MEDIA_CPU_LOCK_PATH", str(tmp_path / "custom.lock"))
    lock_path = _resolve_default_lock_path()
    assert lock_path == tmp_path / "custom.lock"


def test_flite_and_synthetic_fallback(tmp_path: Path):
    orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
    out_f = tmp_path / "flite_out.mp3"

    # 1. Flite success
    with patch("subprocess.run") as mock_sub:
        def side_effect(cmd, **kwargs):
            out_f.write_bytes(b"FLITE_AUDIO")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_sub.side_effect = side_effect
        res = orch._invoke_flite("Hello agent", out_f, "slt")
        assert res.success is True
        assert res.data["provider"] == "flite"

    # 2. Flite failure triggers sine fallback
    out_sine = tmp_path / "sine_out.mp3"
    with patch("subprocess.run") as mock_sub:
        call_count = 0

        def sine_side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(returncode=1, stdout="", stderr="Flite error")
            out_sine.write_bytes(b"SINE_AUDIO")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_sub.side_effect = sine_side_effect
        res = orch._invoke_flite("Synthetic fallback text", out_sine, "rms")
        assert res.success is True
        assert res.data["provider"] == "flite"


def test_edge_tts_settings_and_invocation(tmp_path: Path):
    orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")
    # Rate resolution
    assert orch._resolve_edge_rate({"rate": "+10%"}) == "+10%"
    assert orch._resolve_edge_rate({"speed": 1.2}) == "+20%"
    assert orch._resolve_edge_rate({"speed": 0.9}) == "-10%"

    # Build args
    txt_file = tmp_path / "text.txt"
    txt_file.write_text("Hello edge")
    out_edge = tmp_path / "edge_out.mp3"
    args = orch._build_edge_args(txt_file, out_edge, "en-US-ChristopherNeural", {"rate": "+5%", "pitch": "+2Hz"})
    assert "--voice" in args
    assert "en-US-ChristopherNeural" in args
    assert "--rate" in args
    assert "+5%" in args
    assert "--pitch" in args
    assert "+2Hz" in args

    # Invoke edge success
    with patch("subprocess.run") as mock_sub:
        def mock_edge(cmd, **kwargs):
            out_edge.write_bytes(b"EDGE_AUDIO")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_sub.side_effect = mock_edge
        res = orch._invoke_edge("Hello edge", out_edge, "en-US-ChristopherNeural", None)
        assert res.success is True
        assert res.data["provider"] == "edge"
