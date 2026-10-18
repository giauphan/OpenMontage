"""Post-render verification for HookGuard."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

from lib.hook_guard.canonical_edl import verify_body_edl_preservation

logger = logging.getLogger(__name__)


def probe_rendered_video(video_path: Path | str) -> dict[str, Any]:
    """Inspect rendered video using ffprobe."""
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size == 0:
        return {"error": f"Video file missing or empty: {path}"}

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return {"error": f"ffprobe failed: {proc.stderr}"}
        data = json.loads(proc.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        return {
            "duration_seconds": float(fmt.get("duration", 0.0)),
            "size_bytes": int(fmt.get("size", 0)),
            "width": int(v_stream.get("width", 0)) if v_stream else 0,
            "height": int(v_stream.get("height", 0)) if v_stream else 0,
            "has_video": bool(v_stream),
            "has_audio": bool(a_stream),
        }
    except Exception as exc:
        return {"error": str(exc)}


def check_first_seconds_black(video_path: Path | str, max_check_seconds: float = 2.0) -> bool:
    """Return True if first seconds are entirely black frames (blank/black screen)."""
    path = Path(video_path)
    if not path.is_file():
        return True

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-t", str(max_check_seconds),
        "-i", str(path),
        "-vf", "blackdetect=d=0.5:pix_th=0.10",
        "-f", "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        # If blackdetect finds black spanning the full duration:
        if "black_start:0" in proc.stderr and f"black_duration:{max_check_seconds}" in proc.stderr:
            return True
        return False
    except Exception:
        return False


def verify_post_render(
    video_path: Path | str,
    expected_duration: float,
    baseline_body_edl_sha256: str,
    mutated_edl: dict[str, Any],
    mode: str = "overlay",
    preroll_duration: float = 0.0,
    tolerance_seconds: float = 0.5,
) -> tuple[bool, Optional[str], dict[str, Any]]:
    """Execute postflight checks on rendered video.
    
    Checks:
      1. Output file exists and valid size.
      2. Actual output duration matches expected within tolerance.
      3. No blank/black frames in first seconds.
      4. Canonical body EDL fingerprint is preserved.
    """
    probe = probe_rendered_video(video_path)
    if "error" in probe:
        return False, "REJECTED_POST_RENDER_FAILED", {"error": probe["error"]}

    actual_dur = probe.get("duration_seconds", 0.0)
    dur_diff = abs(actual_dur - expected_duration)
    if dur_diff > tolerance_seconds:
        return False, "REJECTED_POST_RENDER_FAILED", {
            "error": f"Output duration {actual_dur:.2f}s differs from expected {expected_duration:.2f}s by {dur_diff:.2f}s (tolerance {tolerance_seconds}s)",
            "probe": probe,
        }

    if check_first_seconds_black(video_path):
        return False, "REJECTED_POST_RENDER_FAILED", {
            "error": "Rendered video starts with blank/black frames",
            "probe": probe,
        }

    # Verify canonical body EDL preservation once more
    ok_edl, edl_err = verify_body_edl_preservation(
        baseline_body_edl_sha256,
        mutated_edl,
        mode=mode,
        preroll_duration=preroll_duration,
    )
    if not ok_edl:
        return False, "REJECTED_BODY_EDL_MUTATED", {
            "error": edl_err,
            "probe": probe,
        }

    return True, None, {"probe": probe, "status": "VERIFIED"}
