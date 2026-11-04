"""FFmpeg composition and concat demuxer rendering for Fixed Niche videos.

Provides fallback composition rendering for fast offline/CI execution
when HyperFrames is not required or available.
Enforces Clean Architecture module sizing.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NARRATION_MP3_FILENAME = "narration.mp3"


def _build_ffmpeg_filter(
    width: int,
    height: int,
    burn_captions: bool,
    project_dir: Path,
) -> tuple[str, str]:
    """Build FFmpeg video filtergraph and aspect ratio flag."""
    dar_str = "9/16" if (width < height) else "16/9"
    aspect_flag = "9:16" if (width < height) else "16:9"
    vf = (
        f"fps=1,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=#0b1120,"
        f"setsar=1/1,setdar={dar_str},"
        f"format=yuv420p"
    )

    ass_path = project_dir / "artifacts" / "captions.ass"
    srt_path = project_dir / "artifacts" / "captions.srt"
    if burn_captions:
        if ass_path.is_file():
            esc_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += f",ass='{esc_ass}'"
        elif srt_path.is_file():
            esc_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += (
                f",subtitles='{esc_srt}':force_style="
                f"'Fontname=DejaVu Sans,Fontsize=22,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H000B0F19,BorderStyle=1,Outline=2.5,Shadow=0,"
                f"MarginV=120,Alignment=2,MarginL=80,MarginR=80'"
            )
    return vf, aspect_flag


def _resolve_asset_id_for_beat(beat: Dict[str, Any]) -> str:
    """Extract primary asset ID from beat dictionary."""
    if beat.get("asset_id"):
        return beat["asset_id"]
    asset_ids = beat.get("asset_ids")
    return asset_ids[0] if asset_ids else ""


def _find_fallback_asset_file(visuals_dir: Path, aid: str, fallback: Optional[Path]) -> Optional[Path]:
    """Find matching asset file by aid prefix or fallback to default."""
    if not aid:
        return fallback
    svg_cand = visuals_dir / f"{aid}.svg"
    if svg_cand.is_file():
        return svg_cand
    matches = list(visuals_dir.glob(f"{aid}.*"))
    return matches[0] if matches else fallback


def _write_beats_concat_list(
    beats: List[Dict[str, Any]],
    render_dur: float,
    visuals_dir: Path,
    svg_assets: List[Path],
    concat_list: Path,
) -> None:
    """Generate concat demuxer text list matching beat timings."""
    planned_total = float(beats[-1].get("end_s", 0.0)) - float(beats[0].get("start_s", 0.0))
    scale = (render_dur / planned_total) if planned_total > 0 else 1.0
    fallback = svg_assets[0] if svg_assets else None

    with concat_list.open("w", encoding="utf-8") as f:
        for b in beats:
            beat_dur = max(0.1, (float(b.get("end_s", 0.0)) - float(b.get("start_s", 0.0))) * scale)
            aid = _resolve_asset_id_for_beat(b)
            svg_cand = _find_fallback_asset_file(visuals_dir, aid, fallback)
            if svg_cand and svg_cand.is_file():
                f.write(f"file '{svg_cand.resolve()}'\n")
                f.write(f"duration {beat_dur:.3f}\n")

        if svg_assets:
            last_aid = _resolve_asset_id_for_beat(beats[-1])
            last_svg = _find_fallback_asset_file(visuals_dir, last_aid, svg_assets[-1]) or svg_assets[-1]
            f.write(f"file '{last_svg.resolve()}'\n")


def _write_slides_concat_list(
    svg_assets: List[Path],
    slide_dur: float,
    concat_list: Path,
) -> None:
    """Generate concat demuxer text list evenly distributing assets."""
    with concat_list.open("w", encoding="utf-8") as f:
        for svg in svg_assets:
            f.write(f"file '{svg.resolve()}'\n")
            f.write(f"duration {slide_dur:.2f}\n")
        f.write(f"file '{svg_assets[-1].resolve()}'\n")


def _resolve_bgm_path(project_dir: Path) -> Optional[Path]:
    """Find background music track in project assets or repository fallback."""
    project_bgm = project_dir / "assets" / "music-bg.mp3"
    if project_bgm.is_file():
        return project_bgm
    repo_bgm = Path(__file__).resolve().parents[2] / "assets" / "audio" / "music-bg.mp3"
    if repo_bgm.is_file():
        return repo_bgm
    return None


def _build_dynamic_bgm_filter(render_dur: float) -> str:
    """Build dynamic volume filter with tension arc during controversy section."""
    fade_start = max(0.0, render_dur - 1.5)
    return (
        f"volume='if(lt(t,1.5),0.12*t/1.5,"
        f"if(between(t,24,30),0.18,"
        f"if(between(t,30,36),0.07,"
        f"if(gte(t,{fade_start:.2f}),0.12*(1-(t-{fade_start:.2f})/1.5),0.12))))':eval=frame"
    )


def _execute_ffmpeg_concat(
    concat_list: Path,
    audio_path: Path,
    vf: str,
    aspect_flag: str,
    render_dur: float,
    output_mp4: Path,
    bgm_path: Optional[Path] = None,
) -> None:
    """Execute FFmpeg concat render and clean up list file."""
    if bgm_path and bgm_path.is_file():
        bgm_filt = _build_dynamic_bgm_filter(render_dur)
        filter_complex = (
            f"[0:v]{vf}[vout];"
            f"[1:a]volume=1.0[narr];"
            f"[2:a]{bgm_filt}[bgm];"
            f"[narr][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_path),
            "-stream_loop", "-1", "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-threads", "0",
            "-aspect", aspect_flag, "-r", "1", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-t", str(render_dur),
            str(output_mp4),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_path), "-vf", vf, "-threads", "0", "-aspect", aspect_flag, "-r", "1",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-t", str(render_dur), str(output_mp4),
        ]
    subprocess.run(cmd, check=True)
    concat_list.unlink(missing_ok=True)


def _execute_ffmpeg_color(
    width: int,
    height: int,
    audio_path: Path,
    vf: str,
    aspect_flag: str,
    render_dur: float,
    output_mp4: Path,
    bgm_path: Optional[Path] = None,
) -> None:
    """Execute FFmpeg blank-canvas fallback render."""
    drawbox = "drawbox=x=80:y=160:w=920:h=360:color=#1e293b:t=fill,drawbox=x=80:y=600:w=920:h=680:color=#38bdf8@0.35:t=fill"
    vf_color = f"{vf},{drawbox}"
    if bgm_path and bgm_path.is_file():
        bgm_filt = _build_dynamic_bgm_filter(render_dur)
        filter_complex = (
            f"[0:v]{vf_color}[vout];"
            f"[1:a]volume=1.0[narr];"
            f"[2:a]{bgm_filt}[bgm];"
            f"[narr][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=#0b1120:s={width}x{height}:d={render_dur}:r=1",
            "-i", str(audio_path),
            "-stream_loop", "-1", "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-threads", "0",
            "-aspect", aspect_flag, "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-t", str(render_dur),
            str(output_mp4),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=#0b1120:s={width}x{height}:d={render_dur}:r=1",
            "-i", str(audio_path), "-vf", vf_color, "-threads", "0", "-aspect", aspect_flag, "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-t", str(render_dur), str(output_mp4),
        ]
    subprocess.run(cmd, check=True)


def render_ffmpeg_composition(
    project_dir: Path,
    output_mp4: Path,
    render_dur: float,
    width: int = 1080,
    height: int = 1920,
    burn_captions: bool = False,
) -> Path:
    """Render composition via FFmpeg concat demuxer for fast offline/CI execution."""
    visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg")
    flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") not in ("0", "false", "False")
    if (visual_style == "animated_agent_diagram_v1") and flag_enabled:
        raise RuntimeError(
            "CRITICAL: Static slideshow fallback via FFmpeg is strictly forbidden for animated_agent_diagram_v1. "
            "HyperFrames dynamic element-level animation is required."
        )

    project_dir = Path(project_dir).resolve()
    output_mp4 = Path(output_mp4).resolve()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    visuals_dir = project_dir / "assets" / "visuals"
    audio_path = project_dir / "assets" / NARRATION_MP3_FILENAME
    renders_dir = output_mp4.parent

    visual_plan_file = project_dir / "artifacts" / "news_visual_plan.json"
    beats: List[Dict[str, Any]] = []
    if visual_plan_file.is_file():
        try:
            plan_json = json.loads(visual_plan_file.read_text(encoding="utf-8"))
            beats = plan_json.get("beats", [])
        except Exception as e:
            logger.warning(f"Could not load news_visual_plan.json: {e}")

    svg_assets = sorted(visuals_dir.glob("*.svg")) if visuals_dir.is_dir() else []
    vf, aspect_flag = _build_ffmpeg_filter(width, height, burn_captions, project_dir)

    concat_list = renders_dir / "slides_concat.txt"
    bgm_path = _resolve_bgm_path(project_dir)
    if beats:
        _write_beats_concat_list(beats, render_dur, visuals_dir, svg_assets, concat_list)
        try:
            _execute_ffmpeg_concat(concat_list, audio_path, vf, aspect_flag, render_dur, output_mp4, bgm_path=bgm_path)
        except subprocess.CalledProcessError as e:
            logger.warning(f"FFmpeg beats concat render failed ({e}); falling back to color canvas")
            concat_list.unlink(missing_ok=True)
            _execute_ffmpeg_color(width, height, audio_path, vf, aspect_flag, render_dur, output_mp4, bgm_path=bgm_path)
    elif svg_assets:
        _write_slides_concat_list(svg_assets, render_dur / len(svg_assets), concat_list)
        try:
            _execute_ffmpeg_concat(concat_list, audio_path, vf, aspect_flag, render_dur, output_mp4, bgm_path=bgm_path)
        except subprocess.CalledProcessError as e:
            logger.warning(f"FFmpeg slides concat render failed ({e}); falling back to color canvas")
            concat_list.unlink(missing_ok=True)
            _execute_ffmpeg_color(width, height, audio_path, vf, aspect_flag, render_dur, output_mp4, bgm_path=bgm_path)
    else:
        _execute_ffmpeg_color(width, height, audio_path, vf, aspect_flag, render_dur, output_mp4, bgm_path=bgm_path)

    return output_mp4
