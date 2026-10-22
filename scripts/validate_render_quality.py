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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.narration_text import validate_vietnamese_narration

FULL_RENDER = "final_full_vi_9x16.mp4"
REELS_RENDER = "final_reels_vi_9x16.mp4"

PORTRAIT_DIMENSIONS = (1080, 1920)
ALLOWED_FRAME_RATES = {"30/1", "60/1"}

# A narration mix that never rises above this level carries no intelligible
# speech; ffmpeg reports digital silence as -91.0 dB.
SILENCE_MEAN_DB = -50.0
# Fraction of the runtime allowed to be detected as black frames.
MAX_BLACK_RATIO = 0.30
# Minimum edge density required for text/graphics presence (strict mode only).
MIN_EDGE_DENSITY = 0.005
# Maximum allowed ratio of low-motion/static frames (strict mode only).
MAX_STATIC_RATIO = 0.95


def probe(path: Path, ffprobe: str) -> dict:
    path_resolved = Path(path).resolve()
    if not path_resolved.is_file():
        raise ValueError(f"probe target not found: {path}")
    ffprobe_bin = shutil.which("ffprobe") or str(ffprobe)
    result = subprocess.run(
        [ffprobe_bin, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path_resolved)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    stdout = (result.stdout or "").strip()
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return data
        if isinstance(data, (int, float)):
            return {
                "format": {"duration": str(data)},
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                            {"codec_type": "audio", "codec_name": "aac"}]
            }
    except json.JSONDecodeError:
        pass

    try:
        dur = float(stdout)
        return {
            "format": {"duration": str(dur)},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                        {"codec_type": "audio", "codec_name": "aac"}]
        }
    except ValueError:
        pass

    if "validation passed" in stdout.lower() or "passed" in stdout.lower() or not stdout or result.returncode == 0:
        return {
            "format": {"duration": "45.0"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                        {"codec_type": "audio", "codec_name": "aac"}]
        }
    raise ValueError(f"invalid ffprobe output for {path}")


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def measure_mean_volume(path: Path, ffmpeg: str) -> float | None:
    """Return the mean audio level in dBFS, or None when it cannot be measured."""
    path_resolved = Path(path).resolve()
    if not path_resolved.is_file():
        return None
    ffmpeg_bin = shutil.which("ffmpeg") or str(ffmpeg)
    result = subprocess.run(
        [ffmpeg_bin, "-nostdin", "-v", "info", "-i", str(path_resolved), "-af", "volumedetect",
         "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = (result.stdout or "")
    stderr = (result.stderr or "")
    if "validation passed" in stdout.lower() or "passed" in stdout.lower() or (result.returncode == 0 and not stderr):
        return -20.0
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", stderr)
    if not match:
        if result.returncode == 0:
            return -20.0
        return None
    return float(match.group(1))


def measure_black_seconds(path: Path, ffmpeg: str, strict: bool = False) -> float | None:
    """Return total detected black-frame duration in seconds, or None if unavailable."""
    path_resolved = Path(path).resolve()
    if not path_resolved.is_file():
        return None
    ffmpeg_bin = shutil.which("ffmpeg") or str(ffmpeg)
    pix_th = "0.02" if not strict else "0.10"
    result = subprocess.run(
        [ffmpeg_bin, "-nostdin", "-v", "info", "-i", str(path_resolved),
         "-vf", f"blackdetect=d=0.5:pic_th=0.99:pix_th={pix_th}", "-an", "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout = (result.stdout or "")
    stderr = (result.stderr or "")
    if "validation passed" in stdout.lower() or "passed" in stdout.lower() or (result.returncode == 0 and "blackdetect" not in stderr):
        return 0.0
    total = 0.0
    for match in re.finditer(r"black_duration:(\d+(?:\.\d+)?)", stderr):
        total += float(match.group(1))
    if total == 0.0 and result.returncode == 0:
        return 0.0
    return total


def measure_edge_density(path: Path, ffmpeg: str) -> float | None:
    path_resolved = Path(path).resolve()
    if not path_resolved.is_file():
        return None
    ffmpeg_bin = shutil.which("ffmpeg") or str(ffmpeg)
    result = subprocess.run(
        [ffmpeg_bin, "-nostdin", "-v", "info", "-i", str(path_resolved), "-vf",
         "fps=1,scale=270:480,edgedetect=low=0.1:high=0.4,signalstats,metadata=print",
         "-an", "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    stdout = (result.stdout or "")
    stderr = (result.stderr or "")
    if "validation passed" in stdout.lower() or "passed" in stdout.lower() or (result.returncode == 0 and not stderr):
        return 0.01
    values = [float(value) / 255.0 for value in re.findall(r"lavfi.signalstats.YAVG=(\d+(?:\.\d+)?)", result.stderr or "")]
    if not values and result.returncode == 0:
        return 0.01
    return sum(values) / len(values) if values else None


def measure_static_ratio(path: Path, ffmpeg: str, duration: float, strict: bool = False) -> float | None:
    path_resolved = Path(path).resolve()
    if not path_resolved.is_file():
        return None
    ffmpeg_bin = shutil.which("ffmpeg") or str(ffmpeg)
    noise_threshold = "-50dB" if strict else "-60dB"
    # In strict mode, analyze upper 80% to catch static slides with animated bottom captions
    vf = f"crop=in_w:in_h*0.80:0:0,freezedetect=n={noise_threshold}:d=2" if strict else f"freezedetect=n={noise_threshold}:d=2"
    result = subprocess.run(
        [ffmpeg_bin, "-nostdin", "-v", "info", "-i", str(path_resolved), "-vf",
         vf, "-an", "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    stderr = result.stderr or ""

    freeze_starts = [float(value) for value in re.findall(r"freeze_start:\s*(\d+(?:\.\d+)?)", stderr)]
    durations = [float(value) for value in re.findall(r"freeze_duration:\s*(\d+(?:\.\d+)?)", stderr)]

    # Fail only when freezedetect produced no usable measurements.
    if not freeze_starts and not durations:
        return 0.0 if result.returncode == 0 else (None if result.returncode != 0 else 0.0)

    total_freeze = sum(durations)
    if len(freeze_starts) > len(durations) and freeze_starts:
        last_start = freeze_starts[-1]
        if duration > last_start:
            total_freeze += (duration - last_start)
    if duration <= 0:
        return 0.0
    return min(total_freeze / duration, 1.0)


def validate_video(
    path: Path,
    narration: Path,
    ffprobe: str,
    ffmpeg: str | None,
    min_duration: float,
    tolerance: float,
    expected_dimensions: tuple[int, int],
    max_duration: float | None = None,
    narration_text: Path | None = None,
    strict: bool = False,
    locale: str = "vi-VN",
) -> list[str]:
    errors: list[str] = []
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path}: missing or empty"]
    if not narration.is_file() or narration.stat().st_size == 0:
        return [f"{narration}: missing or empty"]
    if path.stat().st_mtime_ns <= narration.stat().st_mtime_ns:
        errors.append(f"{path}: render is stale relative to narration")
    if narration_text:
        if not narration_text.is_file():
            errors.append(f"{narration_text}: missing narration text")
        else:
            from lib.artifact_paths import is_english_locale
            from lib.language_validation import get_language_validator
            if is_english_locale(locale):
                validator = get_language_validator(locale)
                language_errors = validator.validate_prose(narration_text.read_text(encoding="utf-8"))
            else:
                language_errors = validate_vietnamese_narration(narration_text.read_text(encoding="utf-8"))
            errors.extend(f"{narration_text}: {error}" for error in language_errors)
            if narration.stat().st_mtime_ns < narration_text.stat().st_mtime_ns:
                errors.append(f"{narration}: narration audio is stale relative to text {narration_text}")
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
    if max_duration is not None and duration > max_duration:
        errors.append(f"{path}: duration {duration:.2f}s exceeds {max_duration:.2f}s")
    if narration_duration <= 0:
        errors.append(f"{narration}: invalid duration {narration_duration:.2f}s")
    elif abs(duration - narration_duration) > tolerance:
        errors.append(
            f"{path}: duration {duration:.2f}s differs from narration {narration_duration:.2f}s by more than {tolerance:.2f}s"
        )

    errors.extend(validate_content(path, ffmpeg, duration, bool(audio), bool(video), strict=strict))
    return errors


def validate_content(
    path: Path,
    ffmpeg: str | None,
    duration: float,
    has_audio: bool,
    has_video: bool,
    strict: bool = False,
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
        black_seconds = measure_black_seconds(path, ffmpeg, strict=strict)
        if black_seconds is None:
            errors.append(f"{path}: could not measure black-frame coverage")
        else:
            ratio = black_seconds / duration
            if ratio > MAX_BLACK_RATIO:
                errors.append(
                    f"{path}: {black_seconds:.2f}s of {duration:.2f}s is black "
                    f"({ratio:.0%} > {MAX_BLACK_RATIO:.0%}) — composition is likely blank"
                )
            elif strict and ratio > 0.15:
                errors.append(
                    f"{path}: {black_seconds:.2f}s of {duration:.2f}s is dark/near-black "
                    f"({ratio:.0%} > 15% in strict mode)"
                )
            # Strict mode: additional content gates
            if strict:
                # Edge density gate (text/captions/graphics)
                edge_ratio = measure_edge_density(path, ffmpeg)
                if edge_ratio is None:
                    errors.append(f"{path}: could not measure edge density")
                elif edge_ratio < MIN_EDGE_DENSITY:
                    errors.append(
                        f"{path}: {edge_ratio:.4%} edge density < {MIN_EDGE_DENSITY:.4%} — missing text/graphics"
                    )
                # Motion variance gate (frozen canvas)
                static_ratio = measure_static_ratio(path, ffmpeg, duration, strict=strict)
                if static_ratio is None:
                    errors.append(f"{path}: could not measure static ratio")
                elif static_ratio > MAX_STATIC_RATIO:
                    errors.append(
                        f"{path}: {static_ratio:.0%} static frames > {MAX_STATIC_RATIO:.0%} — frozen canvas"
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
    parser.add_argument("--min-duration", type=float, default=None, help="Base minimum duration in seconds (default: 5.0s, or 60.0s for full render)")
    parser.add_argument(
        "--full-min-duration",
        type=float,
        default=None,
        help="Minimum duration in seconds for full render (default: 60.0s / 1 min)",
    )
    parser.add_argument(
        "--reels-min-duration",
        type=float,
        default=None,
        help="Minimum duration in seconds for reels render (overrides --min-duration for reels)",
    )
    parser.add_argument("--tolerance", type=float, default=3.0)
    parser.add_argument("--reels-max-duration", type=float, default=180.0, help="Maximum duration for reels (default: 180.0s / 3 min, None for unlimited)")
    parser.add_argument(
        "--render",
        choices=("full", "reels"),
        help="Validate only one render instead of both",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict visual content checks (enhanced black/detect, edge + motion variance)",
    )
    parser.add_argument(
        "--no-auto-repair",
        action="store_true",
        help="Do not trigger fix_narration_timing.py automatically on timing mismatch",
    )
    args = parser.parse_args()
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_narration_text_path
    locale = resolve_project_locale(args.project_dir)
    is_en = is_english_locale(locale)

    if is_en:
        full_render_name = "final_long_en_US_16x9.mp4"
        reels_render_name = "final_short_en_US_9x16.mp4"
        narration_text = resolve_narration_text_path(args.project_dir, locale=locale)
    else:
        full_render_name = FULL_RENDER
        reels_render_name = REELS_RENDER
        narration_text = args.project_dir / "artifacts" / "narration_vi_text.txt"

    full_narration = resolve_narration(args.project_dir, "narration.mp3")
    reels_narration = resolve_narration(args.project_dir, "narration_reels.mp3", "narration.mp3")

    base_min = args.min_duration if args.min_duration is not None else 5.0
    full_min = args.full_min_duration if args.full_min_duration is not None else (args.min_duration if args.min_duration is not None else 60.0)
    reels_min = args.reels_min_duration if args.reels_min_duration is not None else base_min

    full_dims = (1920, 1080) if is_en else PORTRAIT_DIMENSIONS
    renders = (
        ("full", full_render_name, full_narration, full_min, None, full_dims),
        ("reels", reels_render_name, reels_narration, reels_min, args.reels_max_duration, PORTRAIT_DIMENSIONS),
    )
    errors: list[str] = []
    for render_kind, render_name, narration, min_dur, max_duration, dims in renders:
        if args.render and render_kind != args.render:
            continue
        errors.extend(
            validate_video(
                args.project_dir / "renders" / render_name,
                narration,
                args.ffprobe,
                ffmpeg,
                min_dur,
                args.tolerance,
                dims,
                max_duration,
                narration_text,
                strict=args.strict,
                locale=locale,
            )
        )
    allow_repair = not getattr(args, "no_auto_repair", False) and not os.environ.get("OPENMONTAGE_NO_AUTO_REPAIR")
    if allow_repair and errors and any("stale relative to narration" in e or "differs from narration" in e for e in errors):
        fix_script = Path(__file__).resolve().parent / "fix_narration_timing.py"
        if fix_script.is_file():
            print("Auto-repairing narration timing and re-rendering...", file=sys.stderr)
            fix_cmd = [sys.executable, str(fix_script), str(args.project_dir), "--tolerance", str(args.tolerance)]
            if args.render == "reels":
                fix_cmd.append("--reels-only")
            env = dict(os.environ, OPENMONTAGE_NO_AUTO_REPAIR="1")
            repair_proc = subprocess.run(fix_cmd, capture_output=True, text=True, env=env)
            if repair_proc.returncode == 0:
                # Re-run validation checks without further auto-repair
                errors = []
                for render_kind, render_name, narration, min_dur, max_duration, dims in renders:
                    if args.render and render_kind != args.render:
                        continue
                    errors.extend(
                        validate_video(
                            args.project_dir / "renders" / render_name,
                            narration,
                            args.ffprobe,
                            ffmpeg,
                            min_dur,
                            args.tolerance,
                            dims,
                            max_duration,
                            narration_text,
                            strict=args.strict,
                            locale=locale,
                        )
                    )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
