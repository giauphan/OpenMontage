#!/usr/bin/env python3
"""Validate rendered HyperFrames outputs before publication."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


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


def validate_video(
    path: Path,
    narration: Path,
    ffprobe: str,
    min_duration: float,
    tolerance: float,
    expected_dimensions: tuple[int, int],
    max_duration: float | None = None,
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
        if frame_rate not in {"30/1", "60/1"}:
            errors.append(f"{path}: expected 30 or 60 fps, got {frame_rate}")
    if audio and audio[0].get("codec_name") != "aac":
        errors.append(f"{path}: expected aac audio, got {audio[0].get('codec_name')}")
    duration = number(rendered.get("format", {}).get("duration"))
    narration_duration = number(spoken.get("format", {}).get("duration"))
    if duration <= min_duration:
        errors.append(f"{path}: duration {duration:.2f}s is not greater than {min_duration:.2f}s")
    if max_duration is not None and duration > max_duration:
        errors.append(f"{path}: duration {duration:.2f}s exceeds {max_duration:.2f}s")
    if narration_duration <= 0:
        errors.append(f"{narration}: invalid duration {narration_duration:.2f}s")
    elif abs(duration - narration_duration) > tolerance:
        errors.append(
            f"{path}: duration {duration:.2f}s differs from narration {narration_duration:.2f}s by more than {tolerance:.2f}s"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--min-duration", type=float, default=30.0)
    parser.add_argument("--tolerance", type=float, default=3.0)
    parser.add_argument("--reels-max-duration", type=float, default=None)
    args = parser.parse_args()
    narration = args.project_dir / "assets" / "narration.mp3"
    if not narration.is_file() or narration.stat().st_size == 0:
        narration = args.project_dir / "assets" / "voice" / "narration.mp3"
    reels_narration = args.project_dir / "hyperframes_reels" / "assets" / "narration.mp3"
    if not reels_narration.is_file() or reels_narration.stat().st_size == 0:
        reels_narration = narration
    errors: list[str] = []
    errors.extend(
        validate_video(
            args.project_dir / "renders" / "final_full_vi_9x16.mp4",
            narration,
            args.ffprobe,
            args.min_duration,
            args.tolerance,
            (1080, 1920),
        )
    )
    errors.extend(
        validate_video(
            args.project_dir / "renders" / "final_reels_vi_9x16.mp4",
            reels_narration,
            args.ffprobe,
            args.min_duration,
            args.tolerance,
            (1080, 1920),
            args.reels_max_duration,
        )
    )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
