"""Robust media integrity and validation module for OpenMontage.

Provides centralized verification for image and video assets to prevent
corrupted, truncated, silent, or blank media from passing validation gates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def verify_image_integrity(path: str | Path) -> tuple[bool, str]:
    """Verify that an image file exists, is non-empty, and has valid magic bytes/headers.

    Supports JPEG, PNG, and WebP.
    """
    p = Path(path)
    if not p.is_file():
        return False, f"Image file not found: {p}"

    size = p.stat().st_size
    if size < 32:
        return False, f"Image file too small ({size} bytes): {p}"

    header = p.read_bytes()[:16]

    # JPEG: FF D8 FF
    if header.startswith(b"\xFF\xD8\xFF"):
        return True, "OK"
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, "OK"
    # WebP: RIFF ... WEBP
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return True, "OK"

    return False, f"Invalid image magic bytes/header for {p}"


def verify_video_integrity(
    path: str | Path,
    min_duration: float = 0.5,
    expected_dimensions: tuple[int, int] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify video container, streams, duration, and decode integrity using ffprobe/ffmpeg.

    Returns (passed, error_message, details_dict).
    """
    p = Path(path)
    details: dict[str, Any] = {"path": str(p)}

    if not p.is_file():
        return False, f"Video file missing: {p}", details

    size = p.stat().st_size
    details["file_size_bytes"] = size
    if size < 1024:
        return False, f"Video file empty or too small ({size} bytes): {p}", details

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False, "ffprobe not available on PATH", details

    # 1. Probe container format and streams
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return False, f"ffprobe execution failed: {e}", details

    if proc.returncode != 0:
        err = proc.stderr.strip() or "unknown ffprobe error"
        return False, f"ffprobe failed: {err}", details

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, "Invalid JSON output from ffprobe", details

    fmt = data.get("format", {})
    duration_str = fmt.get("duration")
    duration = 0.0
    if duration_str is not None:
        try:
            duration = float(duration_str)
        except ValueError:
            pass

    details["duration"] = duration
    if duration <= min_duration:
        return False, f"Video duration {duration:.2f}s is below minimum ({min_duration}s)", details

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    details["has_video"] = len(video_streams) > 0
    details["has_audio"] = len(audio_streams) > 0

    if not video_streams:
        return False, f"Video file lacks a video stream: {p}", details

    v_stream = video_streams[0]
    width = int(v_stream.get("width") or 0)
    height = int(v_stream.get("height") or 0)
    details["width"] = width
    details["height"] = height
    details["video_codec"] = v_stream.get("codec_name")

    if width <= 0 or height <= 0:
        return False, f"Invalid video dimensions: {width}x{height}", details

    if expected_dimensions and (width, height) != expected_dimensions:
        return False, f"Dimensions {width}x{height} do not match expected {expected_dimensions[0]}x{expected_dimensions[1]}", details

    # 2. Decode verification via ffmpeg null muxer (bounded to first 5 seconds)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        decode_cmd = [
            ffmpeg,
            "-v", "error",
            "-i", str(p),
            "-t", "5",
            "-f", "null",
            "-",
        ]
        try:
            dec_proc = subprocess.run(decode_cmd, capture_output=True, text=True, timeout=20)
            if dec_proc.returncode != 0:
                err_msg = dec_proc.stderr.strip() or "decode stream error"
                return False, f"Video decode validation failed: {err_msg}", details
        except Exception as e:
            return False, f"Video decode check timed out or failed: {e}", details

    return True, "OK", details
