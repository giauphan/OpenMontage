"""Regression tests for YouTube Shorts publish route / duration gate / hardcoded paths."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

from tools.publishers.platform_routes import ensure_youtube_short

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPTS))


def _load(name: str):
    __import__("sys").modules.pop(name, None)
    return importlib.import_module(name)


def _create_test_video(path: Path) -> None:
    subprocess.run([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=1080x1920:d=60",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(path),
    ], check=True)


def test_youtube_publisher_enforces_one_minute_min_and_three_minute_max(monkeypatch, tmp_path):
    module = _load("tools.publishers.youtube_publisher")
    video = tmp_path / "short.mp4"
    _create_test_video(video)

    # 1. Under 60 seconds (rejected by 1-minute minimum rule)
    monkeypatch.setattr("tools.publishers.platform_routes.probe_duration", lambda _: 59.5)
    publisher = module.YoutubePublisher()
    result = publisher.execute({"video_path": str(video), "title": "Chiều tin công nghệ AI"})
    assert not result.success
    assert "minimum duration of 60 seconds" in (result.error or "")

    # 2. Over 180 seconds (rejected by YouTube Shorts 3-minute cap)
    monkeypatch.setattr("tools.publishers.platform_routes.probe_duration", lambda _: 180.1)
    result = publisher.execute({"video_path": str(video), "title": "Chiều tin công nghệ AI"})
    assert not result.success
    assert "exceeds the YouTube Shorts limit of 180 seconds" in (result.error or "")
