"""FFmpeg composition rendering: cuts concatenation and timeline assembly.

Handles video-only cuts concatenation, speed scaling, aspect ratio normalization,
audio channel consistency, and subtitle burn-in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tools.base_tool import ToolResult
from tools.video._compose.asset_resolution import is_image
from tools.video._compose.ffmpeg_commands import (
    build_atempo,
    build_subtitle_style,
    resolve_subtitle_style,
)
from tools.video._compose.ffmpeg_effects import has_audio_stream


def compose_cuts(tool: Any, inputs: dict[str, Any]) -> ToolResult:
    """FFmpeg composition: concat video cuts, add audio, burn subtitles."""
    edit_decisions = inputs.get("edit_decisions")
    if not edit_decisions:
        return ToolResult(success=False, error="edit_decisions required for compose")

    output_path = Path(inputs.get("output_path", "composed_output.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path = inputs.get("audio_path")
    subtitle_path = inputs.get("subtitle_path")
    codec = inputs.get("codec", "libx264")
    crf = inputs.get("crf", 23)
    preset = inputs.get("preset", "medium")
    profile_name = inputs.get("profile")

    resolution = "1920x1080"
    fit_mode = "pad"
    compose_target = (edit_decisions.get("metadata") or {}).get("compose_target")
    if isinstance(compose_target, dict):
        try:
            resolution = f"{int(compose_target['width'])}x{int(compose_target['height'])}"
        except (KeyError, ValueError, TypeError):
            pass
        if compose_target.get("fit") in ("pad", "cover"):
            fit_mode = compose_target["fit"]
    if profile_name:
        try:
            from lib.media_profiles import get_profile
            p = get_profile(profile_name)
            resolution = f"{p.width}x{p.height}"
        except (ImportError, ValueError):
            pass
    try:
        target_w, target_h = (int(v) for v in resolution.split("x"))
    except ValueError:
        target_w, target_h = 1920, 1080

    cuts = edit_decisions.get("cuts", [])
    if not cuts:
        return ToolResult(success=False, error="No cuts in edit_decisions")

    playbook_data = inputs.get("playbook")
    resolved_sub_style = resolve_subtitle_style(
        inputs.get("subtitle_style"),
        edit_decisions,
        playbook_data,
    )
    inputs = dict(inputs)
    inputs["subtitle_style"] = resolved_sub_style

    ed_subs = edit_decisions.get("subtitles", {})
    if ed_subs.get("source") and not subtitle_path:
        subtitle_path = ed_subs["source"]

    temp_dir = output_path.parent / ".compose_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_segments: list[Path] = []
    concat_path: Path | None = None
    concat_out: Path | None = None

    try:
        for i, cut in enumerate(cuts):
            source = Path(cut["source"])
            if not source.exists():
                return ToolResult(success=False, error=f"Cut source not found: {source}")

            seg_path = temp_dir / f"seg_{i:04d}.mp4"
            in_s = cut["in_seconds"]
            out_s = cut["out_seconds"]
            duration = out_s - in_s
            speed = cut.get("speed", 1.0)

            if is_image(source):
                return ToolResult(
                    success=False,
                    error=(
                        f"Still image '{source.name}' in cuts. "
                        "Use operation='render' (auto-routes to Remotion) "
                        "or operation='remotion_render' for compositions "
                        "with images, animations, or component scenes."
                    ),
                )

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(in_s),
                "-t", str(duration),
                "-i", str(source),
            ]

            if fit_mode == "cover":
                geom = [
                    f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase",
                    f"crop={target_w}:{target_h}",
                ]
            else:
                geom = [
                    f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black",
                ]
            vf_parts: list[str] = [*geom, "setsar=1", "fps=30"]
            af_parts: list[str] = []
            if speed != 1.0:
                vf_parts.append(f"setpts={1.0/speed}*PTS")
                af_parts.append(build_atempo(speed))

            cmd.extend(["-filter:v", ",".join(vf_parts)])
            if af_parts:
                cmd.extend(["-filter:a", ",".join(af_parts)])

            cmd.extend([
                "-c:v", codec,
                "-crf", str(crf),
                "-preset", preset,
                "-pix_fmt", "yuv420p",
                "-r", "30",
            ])

            has_audio = has_audio_stream(source)
            if has_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(in_s),
                    "-t", str(duration),
                    "-i", str(source),
                    "-f", "lavfi",
                    "-t", str(duration),
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-filter:v", ",".join(vf_parts),
                ]
                if af_parts:
                    cmd.extend(["-filter:a", ",".join(af_parts)])
                cmd.extend([
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", codec,
                    "-crf", str(crf),
                    "-preset", preset,
                    "-pix_fmt", "yuv420p",
                    "-r", "30",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-ar", "48000",
                    "-ac", "2",
                ])

            cmd.append(str(seg_path))
            tool.run_command(cmd)
            temp_segments.append(seg_path)

        concat_path = temp_dir / "concat_list.txt"
        with open(concat_path, "w", encoding="utf-8") as f:
            for seg in temp_segments:
                safe = str(seg.resolve()).replace("\\", "/")
                f.write(f"file '{safe}'\n")

        concat_out = temp_dir / "concat.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_path),
            "-c", "copy",
            str(concat_out),
        ]
        tool.run_command(cmd)

        final_input = concat_out
        vfilters = []

        if subtitle_path and Path(subtitle_path).exists():
            style = inputs.get("subtitle_style", {})
            ass_style = build_subtitle_style(style)
            sub_escaped = str(Path(subtitle_path).resolve()).replace("\\", "/").replace(":", "\\:")
            vfilters.append(f"subtitles='{sub_escaped}':force_style='{ass_style}'")

        cmd = ["ffmpeg", "-y", "-i", str(final_input)]

        if audio_path and Path(audio_path).exists():
            cmd.extend(["-i", audio_path])

        profile_flags: list[str] = []
        if profile_name:
            try:
                from lib.media_profiles import get_profile
                p = get_profile(profile_name)
                profile_flags = ["-s", f"{p.width}x{p.height}", "-r", str(p.fps)]
            except (ImportError, ValueError):
                pass

        needs_reencode = bool(vfilters) or bool(profile_flags)

        if needs_reencode:
            if vfilters:
                cmd.extend(["-vf", ",".join(vfilters)])
            cmd.extend(["-c:v", codec, "-crf", str(crf), "-preset", preset])
            cmd.extend(profile_flags)
        else:
            cmd.extend(["-c:v", "copy"])

        if audio_path and Path(audio_path).exists():
            cmd.extend(["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"])
        else:
            cmd.extend(["-c:a", "copy"])

        cmd.append(str(output_path))
        tool.run_command(cmd)

        return ToolResult(
            success=True,
            data={
                "operation": "compose",
                "cut_count": len(cuts),
                "has_subtitles": subtitle_path is not None,
                "has_mixed_audio": audio_path is not None,
                "profile": profile_name,
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
        )
    finally:
        for f in temp_segments:
            if f.exists():
                f.unlink()
        for f in [concat_path, concat_out]:
            if f is not None and f.exists():
                f.unlink()
        if temp_dir.exists():
            try:
                temp_dir.rmdir()
            except OSError:
                pass


def render_via_ffmpeg(
    tool: Any,
    *,
    inputs: dict[str, Any],
    edit_decisions: dict[str, Any],
    resolved_cuts: list[dict],
    output_path: Path,
    profile: Optional[str],
) -> ToolResult:
    """Explicit FFmpeg-only render path."""
    options = inputs.get("options", {})
    subtitle_burn = options.get("subtitle_burn", True)

    subtitle_path = inputs.get("subtitle_path")
    if subtitle_burn and not subtitle_path:
        ed_subs = edit_decisions.get("subtitles", {})
        if ed_subs.get("enabled") and ed_subs.get("source"):
            subtitle_path = ed_subs["source"]

    compose_inputs = dict(inputs)
    compose_inputs["edit_decisions"] = dict(edit_decisions, cuts=resolved_cuts)
    compose_inputs["output_path"] = str(output_path)
    if subtitle_path:
        compose_inputs["subtitle_path"] = subtitle_path
    if profile:
        compose_inputs["profile"] = profile

    render_result = compose_cuts(tool, compose_inputs)

    if render_result.success and output_path.exists():
        final_review = tool._run_final_review(
            output_path,
            edit_decisions,
            inputs.get("proposal_packet"),
            narration_transcript_path=inputs.get("narration_transcript_path"),
            script_text=inputs.get("script_text") or tool._read_text_file(
                inputs.get("script_path")
            ),
        )
        if render_result.data is None:
            render_result.data = {}
        render_result.data["final_review"] = final_review
        render_result.data["final_review_status"] = final_review["status"]
        if final_review["status"] == "fail":
            return ToolResult(
                success=False,
                error=(
                    "Post-render self-review FAILED (FFmpeg). The output is not presentable.\n"
                    + "\n".join(f"  • {i}" for i in final_review.get("issues_found", []))
                ),
                data=render_result.data,
            )

    return render_result
