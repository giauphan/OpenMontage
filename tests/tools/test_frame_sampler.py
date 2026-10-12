"""Tests for tools/analysis/frame_sampler.py hardening."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.analysis.frame_sampler import FrameSampler


class TestFrameSamplerHardening:
    def test_missing_input_file(self, tmp_path):
        tool = FrameSampler()
        res = tool.execute({"input_path": str(tmp_path / "missing.mp4"), "strategy": "count"})
        assert res.success is False
        assert "not found" in res.error.lower()

    def test_zero_duration_returns_failure(self, tmp_path):
        tool = FrameSampler()
        vid = tmp_path / "zero.mp4"
        vid.write_bytes(b"x" * 2000)

        with patch.object(tool, "_get_duration", return_value=0.0):
            res = tool.execute({
                "input_path": str(vid),
                "strategy": "count",
                "count": 5,
                "output_dir": str(tmp_path / "frames"),
            })
            assert res.success is False
            assert "duration" in res.error.lower() or "0 frames" in res.error.lower()

    def test_ffmpeg_extraction_error_propagates(self, tmp_path):
        tool = FrameSampler()
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)

        with patch.object(tool, "_get_duration", return_value=10.0), \
             patch.object(tool, "run_command", side_effect=RuntimeError("ffmpeg failed to decode")):
            res = tool.execute({
                "input_path": str(vid),
                "strategy": "count",
                "count": 5,
                "output_dir": str(tmp_path / "frames"),
            })
            assert res.success is False
            assert "ffmpeg failed" in res.error.lower()

    def test_corrupted_extracted_frames_rejected(self, tmp_path):
        tool = FrameSampler()
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        out_dir = tmp_path / "frames"

        def mock_extract(cmd):
            # Create corrupted non-image frame
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "frame_0001.jpg").write_bytes(b"corrupted data")

        with patch.object(tool, "_get_duration", return_value=10.0), \
             patch.object(tool, "run_command", side_effect=mock_extract):
            res = tool.execute({
                "input_path": str(vid),
                "strategy": "count",
                "count": 1,
                "output_dir": str(out_dir),
            })
            assert res.success is False
            assert "corrupt" in res.error.lower() or "no valid" in res.error.lower() or "invalid" in res.error.lower()

    def test_valid_extracted_frames_succeed(self, tmp_path):
        tool = FrameSampler()
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        out_dir = tmp_path / "frames"

        def mock_extract(cmd):
            out_dir.mkdir(parents=True, exist_ok=True)
            # Create valid JPEG magic bytes
            (out_dir / "frame_0001.jpg").write_bytes(b"\xFF\xD8\xFF" + b"\x00" * 100)

        with patch.object(tool, "_get_duration", return_value=10.0), \
             patch.object(tool, "run_command", side_effect=mock_extract):
            res = tool.execute({
                "input_path": str(vid),
                "strategy": "count",
                "count": 1,
                "output_dir": str(out_dir),
            })
            assert res.success is True
            assert res.data["frame_count"] == 1
            assert len(res.data["frames"]) == 1
