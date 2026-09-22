"""Regression tests for YouTube Shorts publish route / duration gate / hardcoded paths."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

from tools.publishers.platform_routes import CUT_RENDER, FULL_RENDER, ensure_youtube_short

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


def test_publish_slot_uses_cut_render_for_short_jobs():
    module = _load("publish_slot")
    for job_name, job in module.JOBS.items():
        if job["kind"] == "short" and job["platform"] == "youtube":
            assert job["path"].endswith(CUT_RENDER), f"{job_name} uses {job['path']} instead of {CUT_RENDER}"


def test_publish_slot_instagram_uses_full_render():
    module = _load("publish_slot")
    for job_name, job in module.JOBS.items():
        if job["kind"] == "reels" and job["platform"] == "instagram":
            assert job["path"].endswith(FULL_RENDER), f"{job_name} uses {job['path']} instead of {FULL_RENDER}"


def test_youtube_publisher_rejects_over_sixty_seconds(monkeypatch, tmp_path):
    module = _load("tools.publishers.youtube_publisher")
    video = tmp_path / "short.mp4"
    _create_test_video(video)
    monkeypatch.setattr("tools.publishers.platform_routes.probe_duration", lambda _: 60.01)

    publisher = module.YoutubePublisher()
    result = publisher.execute({"video_path": str(video), "title": "Title #Shorts"})
    assert not result.success
    assert "60 seconds" in (result.error or "")
