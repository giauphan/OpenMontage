from pathlib import Path

import pytest

from tools.publishers.platform_routes import (
    CUT_RENDER,
    FULL_RENDER,
    PLATFORM_ROUTES,
    ensure_vertical,
    ensure_youtube_short,
)


def test_platform_routes_match_policy():
    assert PLATFORM_ROUTES["youtube"][1:] == ("yt_shorts", CUT_RENDER)
    assert PLATFORM_ROUTES["tiktok"][1:] == ("tiktok", FULL_RENDER)
    assert PLATFORM_ROUTES["facebook"][1:] == ("fb_video", FULL_RENDER)
    assert PLATFORM_ROUTES["instagram"][1:] == ("ig_reels", CUT_RENDER)
    assert all("16x9" not in render for _, _, render in PLATFORM_ROUTES.values())


def test_youtube_short_route_uses_short_cut():
    kind, _, render = PLATFORM_ROUTES["youtube"]
    assert kind == "short"
    assert render == CUT_RENDER


def test_youtube_short_rejects_video_over_sixty_seconds(monkeypatch, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("tools.publishers.platform_routes.probe_duration", lambda _: 60.01)

    with pytest.raises(ValueError, match="60 seconds"):
        ensure_youtube_short(video)


def test_youtube_short_accepts_sixty_second_video(monkeypatch, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("tools.publishers.platform_routes.probe_duration", lambda _: 60.0)

    ensure_youtube_short(video)


def test_ensure_vertical_rejects_missing():
    with pytest.raises(ValueError, match="video not found"):
        ensure_vertical(Path("/does/not/exist.mp4"))
