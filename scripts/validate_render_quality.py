#!/usr/bin/env python3
"""Validate rendered HyperFrames outputs before publication.

Container metadata alone does not prove a video is watchable. A 1080x1920
h264/aac file can still be an all-black frame sequence with a silent audio
track, and every metadata-only check would pass it. This gate therefore
inspects decoded content as well:

  * technical contract — dimensions, codecs, frame rate, duration
  * audio content      — the mix must not be effectively silent
  * video content      — the frames must not be predominantly black

Both the full render and the Reels render are validated. By default they are
both compared against the project narration; a Reels-specific narration at
``assets/narration_reels.mp3`` overrides that for the Reels render so a genuine
short excerpt is not forced to the full story length.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

FULL_RENDER = "final_full_vi_9x16.mp4"
REELS_RENDER = "final_reels_vi_9x16.mp4"

PORTRAIT_DIMENSIONS = (1080, 1920)
ALLOWED_FRAME_RATES = {"30/1", "60/1"}

# A narration mix that never rises above this level carries no intelligible
# speech; ffmpeg reports digital silence as -91.0 dB.
SILENCE_MEAN_DB = -50.0
# Fraction of the runtime allowed to be detected as black frames.
MAX_BLACK_RATIO = 0.30


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid ffprobe output for {path}") from exc


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def measure_mean_volume(path: Path, ffmpeg: str) -> float | None:
    """Return the mean audio level in dBFS, or None when it cannot be measured."""
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "info", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr or "")
    if not match:
        return None
    return float(match.group(1))


def measure_black_seconds(path: Path, ffmpeg: str) -> float | None:
    """Return total detected black-frame duration in seconds, or None if unavailable."""
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "info", "-i", str(path),
         "-vf", "blackdetect=d=0.5:pic_th=0.98:pix_th=0.10", "-an", "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    stderr = result.stderr or ""
    if "blackdetect" not in stderr and result.returncode != 0:
        return None
    total = 0.0
    for match in re.finditer(r"black_duration:(\d+(?:\.\d+)?)", stderr):
        total += float(match.group(1))
    return total


def validate_video(
    path: Path,
    narration: Path,
    ffprobe: str,
    ffmpeg: str | None,
    min_duration: float,
    tolerance: float,
    expected_dimensions: tuple[int, int],
) -> list[str]:
    errors: list[str] = []
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path}: missing or empty"]
    if not narration.is_file() or narration.stat().st_size == 0:
        return [f"{narration}: missing or empty"]
    if path.stat().st_mtime_ns <= narration.stat().st_mtime_ns:
        errors.append(f"{path}: render is stale relative to narration")
    try:
        rendered = probe(path, ffprobe)
        spoken = probe(narration, ffprobe)
    except ValueError as exc:
        return errors + [str(exc)]

    streams = rendered.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not video:
        errors.append(f"{path}: no video stream")
    if not audio:
        errors.append(f"{path}: no audio stream")
    if video:
        stream = video[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if (width, height) != expected_dimensions:
            errors.append(
                f"{path}: expected {expected_dimensions[0]}x{expected_dimensions[1]} video, got {width}x{height}"
            )
        if stream.get("codec_name") != "h264":
            errors.append(f"{path}: expected h264 video, got {stream.get('codec_name')}")
        frame_rate = stream.get("r_frame_rate")
        if frame_rate not in ALLOWED_FRAME_RATES:
            errors.append(f"{path}: expected 30 or 60 fps, got {frame_rate}")
    if audio and audio[0].get("codec_name") != "aac":
        errors.append(f"{path}: expected aac audio, got {audio[0].get('codec_name')}")
    duration = number(rendered.get("format", {}).get("duration"))
    narration_duration = number(spoken.get("format", {}).get("duration"))
    if duration <= min_duration:
        errors.append(f"{path}: duration {duration:.2f}s is not greater than {min_duration:.2f}s")
    if narration_duration <= 0:
        errors.append(f"{narration}: invalid duration {narration_duration:.2f}s")
    elif abs(duration - narration_duration) > tolerance:
        errors.append(
            f"{path}: duration {duration:.2f}s differs from narration {narration_duration:.2f}s by more than {tolerance:.2f}s"
        )

    errors.extend(validate_content(path, ffmpeg, duration, bool(audio), bool(video)))
    return errors


def validate_content(
    path: Path,
    ffmpeg: str | None,
    duration: float,
    has_audio: bool,
    has_video: bool,
) -> list[str]:
    """Decode-level checks that catch silent mixes and blank visuals."""
    if ffmpeg is None:
        return [f"{path}: ffmpeg unavailable, cannot verify audio/video content"]

    errors: list[str] = []
    if has_audio:
        mean_db = measure_mean_volume(path, ffmpeg)
        if mean_db is None:
            errors.append(f"{path}: could not measure audio level")
        elif mean_db <= SILENCE_MEAN_DB:
            errors.append(
                f"{path}: audio is effectively silent (mean volume {mean_db:.1f} dB <= {SILENCE_MEAN_DB:.1f} dB)"
            )
    if has_video and duration > 0:
        black_seconds = measure_black_seconds(path, ffmpeg)
        if black_seconds is None:
            errors.append(f"{path}: could not measure black-frame coverage")
        else:
            ratio = black_seconds / duration
            if ratio > MAX_BLACK_RATIO:
                errors.append(
                    f"{path}: {black_seconds:.2f}s of {duration:.2f}s is black "
                    f"({ratio:.0%} > {MAX_BLACK_RATIO:.0%}) — composition is likely blank"
                )
    return errors


def resolve_narration(project_dir: Path, *candidates: str) -> Path:
    """Return the first existing non-empty narration path, else the first candidate."""
    paths = [project_dir / "assets" / name for name in candidates]
    paths.append(project_dir / "assets" / "voice" / "narration.mp3")
    for path in paths:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return paths[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="ffmpeg binary used for decode-level audio/video content checks",
    )
    parser.add_argument("--min-duration", type=float, default=30.0)
    parser.add_argument("--tolerance", type=float, default=3.0)
    args = parser.parse_args()

    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")

    full_narration = resolve_narration(args.project_dir, "narration.mp3")
    reels_narration = resolve_narration(args.project_dir, "narration_reels.mp3", "narration.mp3")

    errors: list[str] = []
    for render_name, narration in (
        (FULL_RENDER, full_narration),
        (REELS_RENDER, reels_narration),
    ):
        errors.extend(
            validate_video(
                args.project_dir / "renders" / render_name,
                narration,
                args.ffprobe,
                ffmpeg,
                args.min_duration,
                args.tolerance,
                PORTRAIT_DIMENSIONS,
            )
        )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
