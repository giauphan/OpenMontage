"""Tests for lib/media_integrity.py."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.media_integrity import verify_image_integrity, verify_video_integrity


class TestImageIntegrity:
    def test_missing_file(self, tmp_path):
        ok, msg = verify_image_integrity(tmp_path / "nonexistent.jpg")
        assert ok is False
        assert "not found" in msg.lower()

    def test_too_small_file(self, tmp_path):
        tiny = tmp_path / "tiny.jpg"
        tiny.write_bytes(b"small")
        ok, msg = verify_image_integrity(tiny)
        assert ok is False
        assert "too small" in msg.lower()

    def test_invalid_magic_bytes(self, tmp_path):
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"0" * 100)
        ok, msg = verify_image_integrity(bad)
        assert ok is False
        assert "magic bytes" in msg.lower()

    def test_valid_jpeg(self, tmp_path):
        jpg = tmp_path / "valid.jpg"
        jpg.write_bytes(b"\xFF\xD8\xFF" + b"\x00" * 100)
        ok, msg = verify_image_integrity(jpg)
        assert ok is True
        assert msg == "OK"

    def test_valid_png(self, tmp_path):
        png = tmp_path / "valid.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        ok, msg = verify_image_integrity(png)
        assert ok is True
        assert msg == "OK"

    def test_valid_webp(self, tmp_path):
        webp = tmp_path / "valid.webp"
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100)
        ok, msg = verify_image_integrity(webp)
        assert ok is True
        assert msg == "OK"


class TestVideoIntegrity:
    def test_missing_video(self, tmp_path):
        ok, msg, details = verify_video_integrity(tmp_path / "missing.mp4")
        assert ok is False
        assert "missing" in msg.lower()

    def test_empty_or_tiny_video(self, tmp_path):
        tiny = tmp_path / "tiny.mp4"
        tiny.write_bytes(b"tiny")
        ok, msg, details = verify_video_integrity(tiny)
        assert ok is False
        assert "too small" in msg.lower() or "empty" in msg.lower()

    @patch("shutil.which")
    def test_ffprobe_missing(self, mock_which, tmp_path):
        mock_which.return_value = None
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid)
        assert ok is False
        assert "ffprobe not available" in msg

    @patch("shutil.which", return_value="/usr/bin/ffprobe")
    @patch("subprocess.run")
    def test_ffprobe_failure(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="Invalid data found", stdout="")
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid)
        assert ok is False
        assert "ffprobe failed" in msg

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_video_too_short(self, mock_run, mock_which, tmp_path):
        mock_which.side_effect = lambda bin: f"/usr/bin/{bin}"
        payload = {
            "format": {"duration": "0.2"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid, min_duration=0.5)
        assert ok is False
        assert "below minimum" in msg

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_no_video_stream(self, mock_run, mock_which, tmp_path):
        mock_which.side_effect = lambda bin: f"/usr/bin/{bin}"
        payload = {
            "format": {"duration": "5.0"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid)
        assert ok is False
        assert "lacks a video stream" in msg

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_decode_failure(self, mock_run, mock_which, tmp_path):
        mock_which.side_effect = lambda bin: f"/usr/bin/{bin}"
        payload = {
            "format": {"duration": "5.0"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
        }
        # First call is ffprobe (success), second call is ffmpeg decode (failure)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps(payload), stderr=""),
            MagicMock(returncode=1, stdout="", stderr="Corrupt packet at EOF"),
        ]
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid)
        assert ok is False
        assert "decode validation failed" in msg.lower()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_valid_video(self, mock_run, mock_which, tmp_path):
        mock_which.side_effect = lambda bin: f"/usr/bin/{bin}"
        payload = {
            "format": {"duration": "5.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps(payload), stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"x" * 2000)
        ok, msg, details = verify_video_integrity(vid, expected_dimensions=(1080, 1920))
        assert ok is True
        assert msg == "OK"
        assert details["has_video"] is True
        assert details["has_audio"] is True
