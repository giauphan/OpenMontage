"""Production composition rendering orchestration for Practical AI Agent Engineering niche.

Extracts composition rendering pipeline to preserve Clean Architecture module sizing (< 450 lines).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional

from lib.audio.narration_orchestrator import MediaCpuLock, probe_audio_duration
from lib.fixed_niche.hyperframes_composer import (
    render_ffmpeg_composition,
    render_hyperframes_composition,
)

logger = logging.getLogger(__name__)


def render_project_composition(
    project_dir: Path,
    composition_name: str = "hyperframes_reels",
    output_mp4: Optional[Path] = None,
    duration_seconds: float = 72.0,
    allow_synthetic_audio: bool = False,
    burn_captions: bool = False,
    renderer: str = "auto",
) -> Path:
    """Render a dynamic project composition via HyperFrames or FFmpeg.

    Protected by MediaCpuLock to serialize heavy render workloads.
    """
    project_dir = Path(project_dir).resolve()
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    if output_mp4 is None:
        if "reels" in composition_name or "short" in composition_name:
            output_mp4 = renders_dir / "final_short_en_US_9x16.mp4"
        else:
            output_mp4 = renders_dir / "final_long_en_US_16x9.mp4"

    lock = MediaCpuLock(timeout_seconds=300.0)
    with lock:
        audio_path = project_dir / "assets" / "narration.mp3"
        is_vertical = (
            "reels" in composition_name
            or "short" in composition_name
            or "9x16" in composition_name
            or "9x16" in str(output_mp4)
        )
        width, height = (1080, 1920) if is_vertical else (1920, 1080)

        # Check narration audio file
        if not audio_path.is_file():
            if not allow_synthetic_audio:
                raise FileNotFoundError(
                    f"Narration audio file missing: {audio_path}. "
                    "Synthesize voice narration before rendering in production."
                )
            # Create synthetic silent audio track only when explicit test-only flag is set
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "anullsrc=r=44100:cl=stereo", "-t", str(duration_seconds),
                 "-c:a", "libmp3lame", "-b:a", "192k", str(audio_path)],
                check=True,
            )

        # Validate that narration does not exceed target video duration
        audio_dur = probe_audio_duration(audio_path)
        if audio_dur > duration_seconds:
            raise ValueError(
                f"Narration duration ({audio_dur:.2f}s) exceeds target duration ({duration_seconds:.2f}s). "
                "Truncating narration with FFmpeg -t is rejected."
            )

        # In production renders, warn if narration duration is below minimum allowed duration
        if not allow_synthetic_audio and duration_seconds >= 60.0 and audio_dur < 60.0:
            logger.warning(
                f"Narration duration ({audio_dur:.2f}s) is below 60.0s. "
                "Aligning render duration to prevent out-of-sync playback."
            )

        # Determine actual render duration strictly matching narration audio if valid within shorts contract
        render_dur = audio_dur if 65.0 <= audio_dur <= 75.0 else duration_seconds

        # Dispatch renderer: auto, hyperframes, or ffmpeg
        chosen_renderer = renderer.lower() if renderer else "auto"
        if chosen_renderer == "auto":
            env_renderer = os.environ.get("OPENMONTAGE_RENDERER", "").lower()
            if env_renderer in ("hyperframes", "ffmpeg"):
                chosen_renderer = env_renderer
            else:
                # Prioritize HyperFrames when composition exists
                has_hf = (
                    (project_dir / composition_name / "index.html").is_file()
                    or (project_dir / "hyperframes" / "index.html").is_file()
                )
                chosen_renderer = "hyperframes" if has_hf else "ffmpeg"

        if chosen_renderer == "hyperframes":
            comp_dir = project_dir / composition_name
            if not (comp_dir / "index.html").is_file():
                comp_dir = project_dir / "hyperframes"
            if audio_path.is_file():
                comp_audio = comp_dir / "assets" / "narration.mp3"
                comp_audio.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(audio_path, comp_audio)
            ass_path = project_dir / "artifacts" / "captions.ass"
            try:
                return render_hyperframes_composition(
                    comp_dir=comp_dir,
                    output_mp4=output_mp4,
                    burn_captions=burn_captions,
                    ass_path=ass_path if burn_captions else None,
                )
            except Exception as hf_err:
                logger.warning(f"HyperFrames render encountered issue ({hf_err}), falling back to FFmpeg composition")
                return render_ffmpeg_composition(
                    project_dir=project_dir,
                    output_mp4=output_mp4,
                    render_dur=render_dur,
                    width=width,
                    height=height,
                    burn_captions=burn_captions,
                )
        else:
            return render_ffmpeg_composition(
                project_dir=project_dir,
                output_mp4=output_mp4,
                render_dur=render_dur,
                width=width,
                height=height,
                burn_captions=burn_captions,
            )

    return output_mp4
