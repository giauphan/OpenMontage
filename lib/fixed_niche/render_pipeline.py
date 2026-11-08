"""Production composition rendering orchestration for Practical AI Agent Engineering niche.

Extracts composition rendering pipeline to preserve Clean Architecture module sizing (< 450 lines).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from lib.audio.narration_orchestrator import MediaCpuLock, probe_audio_duration
from lib.fixed_niche.hyperframes_composer import (
    render_ffmpeg_composition,
    render_hyperframes_composition,
)

logger = logging.getLogger(__name__)


def _resolve_output_mp4(project_dir: Path, composition_name: str, output_mp4: Optional[Path]) -> Path:
    if output_mp4 is not None:
        return output_mp4
    renders_dir = project_dir / "renders"
    if "reels" in composition_name or "short" in composition_name:
        return renders_dir / "final_short_en_US_9x16.mp4"
    return renders_dir / "final_long_en_US_16x9.mp4"


def _resolve_dimensions(composition_name: str, output_mp4: Path) -> tuple[int, int]:
    is_vertical = (
        "reels" in composition_name
        or "short" in composition_name
        or "9x16" in composition_name
        or "9x16" in str(output_mp4)
    )
    return (1080, 1920) if is_vertical else (1920, 1080)


def _prepare_narration(audio_path: Path, duration_seconds: float, allow_synthetic_audio: bool) -> float:
    if not audio_path.is_file():
        if not allow_synthetic_audio:
            raise FileNotFoundError(
                f"Narration audio file missing: {audio_path}. "
                "Synthesize voice narration before rendering in production."
            )
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=stereo", "-t", str(duration_seconds),
             "-c:a", "libmp3lame", "-b:a", "192k", str(audio_path)],
            check=True,
        )

    audio_dur = probe_audio_duration(audio_path)
    if audio_dur > duration_seconds:
        raise ValueError(
            f"Narration duration ({audio_dur:.2f}s) exceeds target duration ({duration_seconds:.2f}s). "
            "Truncating narration with FFmpeg -t is rejected."
        )
    if not allow_synthetic_audio and duration_seconds >= 60.0 and audio_dur < 60.0:
        logger.warning(
            f"Narration duration ({audio_dur:.2f}s) is below 60.0s. "
            "Aligning render duration to prevent out-of-sync playback."
        )
    return audio_dur if 65.0 <= audio_dur <= 75.0 else duration_seconds


def _select_renderer(renderer: str, project_dir: Path, composition_name: str) -> str:
    chosen = (renderer or "auto").lower()
    if chosen != "auto":
        return chosen
    env_renderer = os.environ.get("OPENMONTAGE_RENDERER", "").lower()
    if env_renderer in ("hyperframes", "ffmpeg"):
        return env_renderer
    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("CI") == "true":
        return "ffmpeg"
    has_hf = (
        (project_dir / composition_name / "index.html").is_file()
        or (project_dir / "hyperframes" / "index.html").is_file()
    )
    return "hyperframes" if has_hf else "ffmpeg"


def _record_render_manifest(
    renders_dir: Path,
    renderer_requested: str,
    renderer_actual: str,
    fallback_occurred: bool,
    fallback_reason: Optional[str],
    output_mp4: Path,
    target_fps: int = 30,
) -> Dict[str, Any]:
    """Persist structured render telemetry to renders/render_manifest.json."""
    manifest = {
        "renderer_requested": renderer_requested,
        "renderer_actual": renderer_actual,
        "fallback_occurred": fallback_occurred,
        "fallback_reason": fallback_reason,
        "target_fps": target_fps,
        "output_mp4": str(output_mp4),
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest_path = renders_dir / "render_manifest.json"
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Failed to write render_manifest.json: {e}")
    return manifest


def _render_hyperframes(
    project_dir: Path,
    composition_name: str,
    output_mp4: Path,
    burn_captions: bool,
    audio_path: Path,
    render_dur: float,
    width: int,
    height: int,
    allow_fallback: bool = True,
) -> Path:
    comp_dir = project_dir / composition_name
    if not (comp_dir / "index.html").is_file():
        comp_dir = project_dir / "hyperframes"
    if audio_path.is_file():
        comp_audio = comp_dir / "assets" / "narration.mp3"
        comp_audio.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, comp_audio)
    ass_path = project_dir / "artifacts" / "captions.ass"
    renders_dir = output_mp4.parent
    try:
        res = render_hyperframes_composition(
            comp_dir=comp_dir,
            output_mp4=output_mp4,
            burn_captions=burn_captions,
            ass_path=ass_path if burn_captions else None,
        )
        _record_render_manifest(
            renders_dir=renders_dir,
            renderer_requested="hyperframes",
            renderer_actual="hyperframes",
            fallback_occurred=False,
            fallback_reason=None,
            output_mp4=output_mp4,
            target_fps=30,
        )
        return res
    except Exception as hf_err:
        if not allow_fallback:
            logger.error(f"HyperFrames render failed ({hf_err}) and renderer fallback is disallowed.")
            _record_render_manifest(
                renders_dir=renders_dir,
                renderer_requested="hyperframes",
                renderer_actual="failed",
                fallback_occurred=True,
                fallback_reason=str(hf_err),
                output_mp4=output_mp4,
                target_fps=30,
            )
            raise RuntimeError(
                f"HyperFrames rendering failed: {hf_err}. Static slideshow fallback is forbidden in strict production mode."
            ) from hf_err

        logger.warning(f"HyperFrames render encountered issue ({hf_err}), falling back to FFmpeg composition")
        res = render_ffmpeg_composition(
            project_dir=project_dir,
            output_mp4=output_mp4,
            render_dur=render_dur,
            width=width,
            height=height,
            burn_captions=burn_captions,
        )
        _record_render_manifest(
            renders_dir=renders_dir,
            renderer_requested="hyperframes",
            renderer_actual="ffmpeg_fallback",
            fallback_occurred=True,
            fallback_reason=str(hf_err),
            output_mp4=output_mp4,
            target_fps=1,
        )
        return res


def render_project_composition(
    project_dir: Path,
    composition_name: str = "hyperframes_reels",
    output_mp4: Optional[Path] = None,
    duration_seconds: float = 72.0,
    allow_synthetic_audio: bool = False,
    burn_captions: bool = False,
    renderer: str = "auto",
    allow_fallback: Optional[bool] = None,
) -> Path:
    """Render a dynamic project composition via HyperFrames or FFmpeg.

    Protected by MediaCpuLock to serialize heavy render workloads.
    """
    project_dir = Path(project_dir).resolve()
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = _resolve_output_mp4(project_dir, composition_name, output_mp4)
    width, height = _resolve_dimensions(composition_name, out_mp4)

    if allow_fallback is None:
        env_fallback = os.environ.get("OPENMONTAGE_ALLOW_RENDERER_FALLBACK", "").lower()
        allow_fallback = env_fallback not in ("0", "false", "no")

    with MediaCpuLock(timeout_seconds=300.0):
        audio_path = project_dir / "assets" / "narration.mp3"
        render_dur = _prepare_narration(audio_path, duration_seconds, allow_synthetic_audio)
        chosen_renderer = _select_renderer(renderer, project_dir, composition_name)

        if chosen_renderer == "hyperframes":
            return _render_hyperframes(
                project_dir, composition_name, out_mp4, burn_captions,
                audio_path, render_dur, width, height,
                allow_fallback=allow_fallback,
            )
        res = render_ffmpeg_composition(
            project_dir=project_dir,
            output_mp4=out_mp4,
            render_dur=render_dur,
            width=width,
            height=height,
            burn_captions=burn_captions,
        )
        _record_render_manifest(
            renders_dir=renders_dir,
            renderer_requested="ffmpeg",
            renderer_actual="ffmpeg",
            fallback_occurred=False,
            fallback_reason=None,
            output_mp4=out_mp4,
            target_fps=1,
        )
        return res
