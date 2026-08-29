"""Platform publishing routes and the 9:16 vertical geometry gate.

All output is vertical. YouTube Shorts, TikTok, and Facebook Reels take the full
vertical render; Instagram Reels takes the shorter cut render.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _ffprobe() -> str | None:
    path = shutil.which("ffprobe")
    if path:
        return path
    candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
    return str(candidates[0]) if candidates else None

FULL_RENDER = "renders/final_full_vi_9x16.mp4"
CUT_RENDER = "renders/final_reels_vi_9x16.mp4"

# The full render is the complete vertical NewsNow story. The cut render is
# used by short-form routes that have a duration limit.
# platform -> (publish kind, publish_metadata.json field, render used)
PLATFORM_ROUTES: dict[str, tuple[str, str, str]] = {
    "youtube": ("short", "yt_shorts", CUT_RENDER),
    "tiktok": ("video", "tiktok", FULL_RENDER),
    "facebook": ("reels", "fb_video", FULL_RENDER),
    "instagram": ("reels", "ig_reels", CUT_RENDER),
}

VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
YOUTUBE_SHORT_MAX_SECONDS = 60.0


def metadata_field(platform: str) -> str:
    return PLATFORM_ROUTES[platform][1]


def probe_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream.

    Raises ValueError when the file is missing, unprobeable, or has no video
    stream — publishing must fail closed rather than upload unknown media.
    """
    ffprobe = _ffprobe()
    if not ffprobe:
        raise ValueError("ffprobe is required to validate video geometry")
    if not path.is_file():
        raise ValueError(f"video not found: {path}")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()[:200]}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: no video stream to validate ({exc})") from exc


def probe_duration(path: Path) -> float:
    """Return the container duration in seconds for a media file."""
    ffprobe = _ffprobe()
    if not ffprobe:
        raise ValueError("ffprobe is required to validate video duration")
    if not path.is_file():
        raise ValueError(f"video not found: {path}")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()[:200]}")
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: cannot determine video duration ({exc})") from exc


def ensure_vertical(path: Path) -> None:
    """Reject any asset that is not 9:16 portrait before it reaches a platform."""
    width, height = probe_dimensions(path)
    if width * 16 != height * 9:
        raise ValueError(
            f"{path}: {width}x{height} is not 9:16 vertical; "
            f"only {VERTICAL_WIDTH}x{VERTICAL_HEIGHT}-style portrait media may be published"
        )


def ensure_youtube_short(path: Path) -> None:
    """Reject a video that YouTube would classify as a regular video."""
    duration = probe_duration(path)
    if duration > YOUTUBE_SHORT_MAX_SECONDS:
        raise ValueError(
            f"{path}: {duration:.3f}s exceeds the YouTube Shorts limit of "
            f"{YOUTUBE_SHORT_MAX_SECONDS:.0f} seconds"
        )
