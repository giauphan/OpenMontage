"""FFmpeg effects, stream inspection, and post-processing adapters.

Provides subtitle burning, overlay composition, re-encoding, audio stream
detection, duration probing, and atomic audio muxing.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.base_tool import ToolResult
from tools.video._compose.ffmpeg_commands import build_subtitle_style


def has_audio_stream(path: Path) -> bool:
    """Return True iff ffprobe reports at least one audio stream."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return "audio" in out
    except Exception:
        return False


def probe_video_stream_duration(video_path: Path) -> float:
    """Return the selected video stream's duration in seconds."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "default=nw=1:nk=1",
                str(video_path),
            ],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        raise RuntimeError(f"Could not probe video stream duration for {video_path}: {exc}") from exc

    raw = out.strip()
    if not raw:
        raise RuntimeError(f"No video stream duration reported for {video_path}")

    try:
        duration = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Unparseable video stream duration {raw!r} for {video_path}") from exc

    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"Video stream duration for {video_path} is not finite and positive ({raw!r})")

    return duration


def mux_external_audio(tool: Any, video_path: Path, audio_path: str | Path) -> ToolResult:
    """Atomically replace a rendered video's audio with the approved mix."""
    audio = Path(audio_path).resolve()
    if not audio.is_file():
        return ToolResult(success=False, error=f"Mixed audio not found: {audio}")

    try:
        probe_fn = getattr(tool, "_probe_video_stream_duration", probe_video_stream_duration)
        video_duration = probe_fn(video_path)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))

    mux_timeout = math.ceil(max(60, 2 * video_duration))

    temp_output = video_path.with_name(
        f".{video_path.stem}.audio-mux-{time.time_ns()}{video_path.suffix}"
    )
    try:
        tool.run_command([
            "ffmpeg", "-nostdin", "-y",
            "-i", str(video_path),
            "-i", str(audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-af", f"apad=whole_dur={video_duration:.3f}",
            "-t", f"{video_duration:.3f}",
            "-movflags", "+faststart",
            str(temp_output),
        ], timeout=mux_timeout)
        if not temp_output.is_file():
            return ToolResult(
                success=False,
                error=f"Audio mux completed but output file is missing: {temp_output}",
            )
        temp_output.replace(video_path)
    except subprocess.TimeoutExpired as exc:
        return ToolResult(
            success=False,
            error=f"Audio mux timed out after {mux_timeout}s for {video_path}: {exc}",
        )
    except Exception as exc:
        return ToolResult(success=False, error=f"Could not mux mixed audio: {exc}")
    finally:
        if temp_output.exists():
            temp_output.unlink()

    return ToolResult(
        success=True,
        data={"output": str(video_path), "has_mixed_audio": True},
        artifacts=[str(video_path)],
    )


def burn_subtitles(tool: Any, inputs: dict[str, Any]) -> ToolResult:
    """Burn subtitle file into video."""
    input_path = Path(inputs["input_path"])
    subtitle_path = Path(inputs["subtitle_path"])
    output_path = Path(inputs.get("output_path", str(input_path.with_stem(f"{input_path.stem}_subtitled"))))

    if not input_path.exists():
        return ToolResult(success=False, error=f"Input not found: {input_path}")
    if not subtitle_path.exists():
        return ToolResult(success=False, error=f"Subtitle file not found: {subtitle_path}")

    style = inputs.get("subtitle_style", {})
    ass_style = build_subtitle_style(style)
    sub_escaped = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
    codec = inputs.get("codec", "libx264")
    crf = inputs.get("crf", 23)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", f"subtitles='{sub_escaped}':force_style='{ass_style}'",
        "-c:v", codec, "-crf", str(crf),
        "-c:a", "copy",
        str(output_path),
    ]

    tool.run_command(cmd)

    return ToolResult(
        success=True,
        data={
            "operation": "burn_subtitles",
            "output": str(output_path),
        },
        artifacts=[str(output_path)],
    )


def overlay(tool: Any, inputs: dict[str, Any]) -> ToolResult:
    """Composite overlay images/videos on top of base video."""
    input_path = Path(inputs["input_path"])
    overlays = inputs.get("overlays", [])
    output_path = Path(inputs.get("output_path", str(input_path.with_stem(f"{input_path.stem}_overlay"))))
    codec = inputs.get("codec", "libx264")
    crf = inputs.get("crf", 23)

    if not input_path.exists():
        return ToolResult(success=False, error=f"Input not found: {input_path}")
    if not overlays:
        return ToolResult(success=False, error="No overlays provided")

    input_args = ["-i", str(input_path)]
    filter_parts = []
    prev_label = "0:v"

    for i, ov in enumerate(overlays):
        asset_path = Path(ov["asset_path"])
        if not asset_path.exists():
            return ToolResult(success=False, error=f"Overlay asset not found: {asset_path}")

        input_args.extend(["-i", str(asset_path)])

        x = int(ov.get("x", 0))
        y = int(ov.get("y", 0))
        start = ov.get("start_seconds", 0)
        end = ov.get("end_seconds")

        overlay_input = f"{i + 1}:v"

        if "width" in ov and "height" in ov:
            w = int(ov["width"])
            h = int(ov["height"])
            filter_parts.append(f"[{overlay_input}]scale={w}:{h}[ov_scaled_{i}]")
            overlay_input = f"ov_scaled_{i}"

        enable = f"between(t,{start},{end})" if end else f"gte(t,{start})"
        out_label = f"v{i}"

        filter_parts.append(
            f"[{prev_label}][{overlay_input}]overlay={x}:{y}:enable='{enable}'[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"]
    cmd.extend(input_args)
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", f"[{prev_label}]", "-map", "0:a?"])
    cmd.extend(["-c:v", codec, "-crf", str(crf), "-c:a", "copy"])
    cmd.append(str(output_path))

    tool.run_command(cmd)

    return ToolResult(
        success=True,
        data={
            "operation": "overlay",
            "overlay_count": len(overlays),
            "output": str(output_path),
        },
        artifacts=[str(output_path)],
    )


def encode(tool: Any, inputs: dict[str, Any]) -> ToolResult:
    """Re-encode video with a specific profile/codec settings."""
    input_path = Path(inputs["input_path"])
    output_path = Path(inputs.get("output_path", str(input_path.with_stem(f"{input_path.stem}_encoded"))))
    codec = inputs.get("codec", "libx264")
    crf = inputs.get("crf", 23)
    preset = inputs.get("preset", "medium")
    profile_name = inputs.get("profile")

    if not input_path.exists():
        return ToolResult(success=False, error=f"Input not found: {input_path}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", codec, "-crf", str(crf), "-preset", preset,
        "-c:a", "aac", "-b:a", "192k",
    ]

    if profile_name:
        try:
            from lib.media_profiles import get_profile
            profile = get_profile(profile_name)
            cmd.extend(["-s", f"{profile.width}x{profile.height}"])
            cmd.extend(["-r", str(profile.fps)])
        except (ImportError, ValueError):
            pass

    cmd.append(str(output_path))
    tool.run_command(cmd)

    return ToolResult(
        success=True,
        data={
            "operation": "encode",
            "codec": codec,
            "crf": crf,
            "profile": profile_name,
            "output": str(output_path),
        },
        artifacts=[str(output_path)],
    )
