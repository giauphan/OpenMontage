from pathlib import Path

import pytest

from tools.publishers.platform_routes import (
    CUT_RENDER,
    FULL_RENDER,
    PLATFORM_ROUTES,
    ensure_vertical,
)


def test_platform_routes_match_policy():
    assert PLATFORM_ROUTES["youtube"][1:] == ("yt_shorts", FULL_RENDER)
    assert PLATFORM_ROUTES["tiktok"][1:] == ("tiktok", FULL_RENDER)
    assert PLATFORM_ROUTES["facebook"][1:] == ("fb_video", FULL_RENDER)
    assert PLATFORM_ROUTES["instagram"][1:] == ("ig_reels", CUT_RENDER)
    assert all("16x9" not in render for _, _, render in PLATFORM_ROUTES.values())


def test_ensure_vertical_rejects_missing():
    with pytest.raises(ValueError, match="video not found"):
        ensure_vertical(Path("/does/not/exist.mp4"))
