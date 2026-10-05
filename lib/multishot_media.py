"""Media validation and ordered assembly for the multi-shot pipeline.

TASK 012–015. Reuses the repository's media-profile constants and wraps
FFmpeg/ffprobe with timeouts and structured errors:

  - probe_clip: parse duration/resolution/FPS/codec/pixel-format, run a
    decode validation, and report errors.
  - validate_shot_clip: enforce per-shot duration tolerance.
  - normalize_clip: canonicalize a source clip to the target profile
    (resolution/FPS/codec/pixel format/audio layout), stripping or
    normalizing audio explicitly.
  - build_concat_plan: ordered, fail-closed concat input.
  - ordered_concat: FFmpeg concat of accepted, validated shots in plan
    order with hard cuts, then a re-probe for duration accounting.

All ffmpeg/ffprobe invocations are bounded by a timeout and return
structured errors rather than raising raw subprocess exceptions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from lib.media_profiles import MediaProfile, get_profile
from lib.multishot_schemas import MultishotValidationError


class MediaError(Exception):
    """Structured FFmpeg/ffprobe failure with the offending command's output."""

    def __init__(self, message: str, *, command: Optional[Sequence[str]] = None,
                 returncode: Optional[int] = None, stderr: str = ""):
        super().__init__(message)
        self.message = message
        self.command = list(command) if command else []
        self.returncode = returncode
        self.stderr = stderr


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(
            f"{name} not found on PATH (media gates require execution on a supported host)"
        )
    return path


def _run(cmd: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"media command timed out after {timeout}s", command=cmd) from exc
    except FileNotFoundError as exc:
        raise MediaError(f"media binary not available: {cmd[0]}", command=cmd) from exc


def _parse_rational(value: Optional[str]) -> Optional[float]:
    """Safely parse a rational or numeric rate string like '30000/1001'."""
    if value is None:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den = float(den)
            return float(num) / den if den else None
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------------
# TASK 012 — ffprobe wrapper
# ------------------------------------------------------------------

def probe_clip(path: str | Path, *, timeout: float = 60.0) -> dict[str, Any]:
    """Probe a media file into a structured validation record.

    Returns ``{duration_sec, width, height, fps, video_codec, pixel_format,
    has_audio, has_video, decode_ok, errors}``. ``errors`` is a list of
    human-readable problems (empty when clean).
    """
    ffprobe = _require_binary("ffprobe")
    result = _run(
        [ffprobe, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        timeout=timeout,
    )
    errors: list[str] = []
    probe: dict[str, Any] = {
        "duration_sec": None, "width": None, "height": None, "fps": None,
        "video_codec": None, "pixel_format": None, "has_audio": False,
        "has_video": False, "decode_ok": False, "errors": errors,
    }

    if not Path(path).is_file():
        errors.append(f"file not found: {path}")
        return probe
    if result.returncode != 0:
        errors.append(f"ffprobe failed: {result.stderr.strip()[:300]}")
        return probe

    data = json.loads(result.stdout or "{}")
    fmt = data.get("format", {})
    if fmt.get("duration"):
        try:
            probe["duration_sec"] = float(fmt["duration"])
        except (TypeError, ValueError):
            errors.append("unreadable duration")

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    probe["has_video"] = video_stream is not None
    probe["has_audio"] = audio_stream is not None

    if video_stream is None:
        errors.append("no video stream")
    else:
        probe["video_codec"] = video_stream.get("codec_name")
        probe["pixel_format"] = video_stream.get("pix_fmt")
        probe["width"] = video_stream.get("width")
        probe["height"] = video_stream.get("height")
        rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
        probe["fps"] = _parse_rational(rate)
        if not probe["width"] or not probe["height"]:
            errors.append("invalid video dimensions")

    if probe["duration_sec"] is not None and probe["duration_sec"] <= 0:
        errors.append("duration must be > 0")

    probe["decode_ok"] = _decode_validates(path, timeout=timeout)
    if not probe["decode_ok"]:
        errors.append("decode validation failed")
    return probe


def _decode_validates(path: str | Path, *, timeout: float) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return True
    result = _run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        timeout=timeout,
    )
    return result.returncode == 0


# ------------------------------------------------------------------
# TASK 013 — shot validator
# ------------------------------------------------------------------

def validate_shot_clip(
    probe: dict[str, Any],
    *,
    planned_duration_sec: float,
    tolerance_sec: float = 0.5,
) -> list[str]:
    """Return validation errors for a probed clip against its plan entry."""
    errors = list(probe.get("errors", []))
    duration = probe.get("duration_sec")
    if duration is not None:
        deviation = abs(duration - planned_duration_sec)
        if deviation > tolerance_sec:
            errors.append(
                f"duration {duration:.3f}s deviates from planned "
                f"{planned_duration_sec:.3f}s by {deviation:.3f}s (tolerance {tolerance_sec})"
            )
    return errors


# ------------------------------------------------------------------
# TASK 014 — normalizer
# ------------------------------------------------------------------

def _normalize_args(src: str, dst: str, profile: MediaProfile, *,
                    audio_policy: str) -> list[str]:
    # Scale-to-fit + pad preserves framing without silent distortion.
    vf = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,"
        f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2"
    )
    base = ["-y", "-i", src, "-vf", vf, "-r", str(profile.fps),
            "-c:v", profile.codec, "-crf", str(profile.crf),
            "-pix_fmt", profile.pixel_format]
    if audio_policy == "silent":
        base.append("-an")
    else:  # retained: uniform 48 kHz stereo AAC
        base += ["-c:a", "aac", "-ar", "48000", "-ac", "2"]
    base.append(dst)
    return base


def normalize_clip(
    src: str | Path,
    dst: str | Path,
    profile: MediaProfile,
    *,
    audio_policy: str = "silent",
    timeout: float = 300.0,
    dry_run: bool = False,
) -> list[str]:
    """Normalize ``src`` to the canonical profile; return the ffmpeg argv.

    ``dry_run`` returns the argv without executing. Otherwise the command is
    run with a timeout and a ``MediaError`` is raised on nonzero exit.
    """
    if audio_policy not in {"silent", "retained"}:
        raise ValueError(f"audio_policy must be 'silent' or 'retained'")
    argv = ["ffmpeg"] + _normalize_args(str(src), str(dst), profile, audio_policy=audio_policy)
    if dry_run:
        return argv
    result = _run(argv, timeout=timeout)
    if result.returncode != 0:
        raise MediaError(
            f"normalize failed for {src}", command=argv,
            returncode=result.returncode, stderr=result.stderr[-500:],
        )
    return argv


# ------------------------------------------------------------------
# TASK 015 — ordered concat
# ------------------------------------------------------------------

@dataclass
class ConcatEntry:
    shot_id: str
    order: int
    path: str


def build_concat_plan(
    shot_plan: dict[str, Any],
    normalized_paths: dict[str, str],
) -> list[ConcatEntry]:
    """Build a fail-closed, ordered concat input from validated shots.

    Rejects missing, extra, or duplicate shots and returns entries sorted by
    plan order. ``normalized_paths`` maps shot_id -> normalized clip path.
    """
    shots = shot_plan["shots"]
    planned_ids = [s["id"] for s in shots]
    planned_set = set(planned_ids)
    provided = set(normalized_paths.keys())

    missing = planned_set - provided
    extra = provided - planned_set
    if missing:
        raise MultishotValidationError(f"concat blocked, missing shots: {sorted(missing)}")
    if extra:
        raise MultishotValidationError(f"concat blocked, extra shots: {sorted(extra)}")
    if len(planned_ids) != len(planned_set):
        raise MultishotValidationError("concat blocked, duplicate shot ids in plan")

    orders = {s["id"]: s["order"] for s in shots}
    entries = [ConcatEntry(s["id"], orders[s["id"]], normalized_paths[s["id"]]) for s in shots]
    entries.sort(key=lambda e: e.order)
    return entries


def write_concat_list(entries: Sequence[ConcatEntry], list_path: str | Path) -> None:
    """Write the FFmpeg concat-demuxer input file (hard cuts only)."""
    lines = [f"file '{Path(e.path).as_posix()}'" for e in entries]
    Path(list_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def ordered_concat(
    entries: Sequence[ConcatEntry],
    dst: str | Path,
    profile: MediaProfile,
    *,
    timeout: float = 600.0,
    list_path: Optional[str | Path] = None,
) -> str:
    """Concatenate normalized shots in plan order using the concat demuxer.

    Returns the output path. The caller re-probes for duration accounting.
    """
    if not entries:
        raise MultishotValidationError("cannot concat zero entries")
    lp = list_path or f"{dst}.concat.txt"
    write_concat_list(entries, lp)
    argv = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lp),
        "-c:v", profile.codec, "-crf", str(profile.crf),
        "-pix_fmt", profile.pixel_format, "-r", str(profile.fps),
        "-c:a", "aac",
        str(dst),
    ]
    result = _run(argv, timeout=timeout)
    if result.returncode != 0:
        raise MediaError(
            "ordered concat failed", command=argv,
            returncode=result.returncode, stderr=result.stderr[-500:],
        )
    return str(dst)


def duration_discrepancy(target_sec: float, actual_sec: float) -> float:
    """Absolute gap between the planned and actual assembled duration."""
    return abs(target_sec - actual_sec)
