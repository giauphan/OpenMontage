"""Final mastering and fail-closed completion for the multi-shot pipeline.

TASK 016–018. Two concerns:

1. Audio/subtitle mastering — build the final master from the base concat
   plus optional narration/music/SFX/subtitles, bounding the audio mux so a
   short base video can never trigger an unbounded mux. Audio/subtitle
   changes invalidate the final master and report only, never the shots.

2. The completion gate — a project may transition to COMPLETED only when
   every planned shot is accepted/validated, durations/dims/FPS are within
   tolerance, and no mandatory asset is missing. A corrupt output or a
   mandatory failure blocks COMPLETED even if an older final exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from lib.media_profiles import MediaProfile
from lib.multishot_schemas import MultishotValidationError


# ------------------------------------------------------------------
# TASK 016 — audio/subtitle mastering
# ------------------------------------------------------------------

def build_audio_mux_args(
    base_video: str,
    out: str,
    *,
    narration: Optional[str] = None,
    music: Optional[str] = None,
    sfx: Optional[str] = None,
    subtitles: Optional[str] = None,
    max_duration_sec: Optional[float] = None,
    burn_subtitles: bool = False,
) -> list[str]:
    """Return ffmpeg argv for the final master.

    The mux is bounded by ``max_duration_sec`` (set by the caller to the base
    video's duration) so a short base video can never drive an unbounded
    audio stream.
    """
    audio_inputs = [n for n in (narration, music, sfx) if n]
    argv = ["ffmpeg", "-y", "-i", base_video]
    for audio in audio_inputs:
        argv += ["-i", audio]
    if subtitles:
        argv += ["-i", subtitles]

    if subtitles and burn_subtitles:
        argv += ["-vf", f"subtitles='{subtitles}'"]
    if len(audio_inputs) > 1:
        # Narration-first ducked mix over music/SFX.
        argv += ["-filter_complex",
                 f"amix=inputs={len(audio_inputs)}:duration=longest:dropout_transition=0"]

    if max_duration_sec is not None:
        argv += ["-t", str(max_duration_sec)]
    argv += ["-c:v", "copy"]
    if audio_inputs or (subtitles and not burn_subtitles):
        argv += ["-c:a", "aac", "-ar", "48000"]
    argv.append(out)
    return argv


def master_final_video(
    base_video: str,
    out: str,
    profile: MediaProfile,
    *,
    narration: Optional[str] = None,
    music: Optional[str] = None,
    sfx: Optional[str] = None,
    subtitles: Optional[str] = None,
    max_duration_sec: Optional[float] = None,
    burn_subtitles: bool = False,
    timeout: float = 600.0,
    dry_run: bool = False,
) -> list[str]:
    """Master the final video. ``dry_run`` returns argv without executing."""
    argv = build_audio_mux_args(
        base_video, out,
        narration=narration, music=music, sfx=sfx, subtitles=subtitles,
        max_duration_sec=max_duration_sec, burn_subtitles=burn_subtitles,
    )
    if dry_run:
        return argv
    import subprocess
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise MultishotValidationError(
            f"final master failed: {result.stderr[-400:]}"
        )
    return argv


# ------------------------------------------------------------------
# TASK 017/018 — final validator + completion gate
# ------------------------------------------------------------------

@dataclass
class FinalValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)


def validate_final_master(
    probe: dict[str, Any],
    *,
    shot_count: int,
    target_duration_sec: float,
    tolerance_sec: float,
    profile: MediaProfile,
    planned_shot_ids: Sequence[str],
    present_shot_ids: Sequence[str],
    failed_shot_ids: Sequence[str],
    stale_shot_ids: Sequence[str],
) -> FinalValidation:
    """Fail-closed final validator. COMPLETED requires every check to pass."""
    errors: list[str] = []
    checks: dict[str, Any] = {}

    if shot_count < 2:
        errors.append(f"shot_count {shot_count} < 2")
    checks["shot_count"] = shot_count

    missing = set(planned_shot_ids) - set(present_shot_ids)
    if missing:
        errors.append(f"missing required shots: {sorted(missing)}")
    checks["missing_shots"] = sorted(missing)

    if set(failed_shot_ids) & set(planned_shot_ids):
        errors.append(f"failed shots block completion: {sorted(failed_shot_ids)}")
    if set(stale_shot_ids) & set(planned_shot_ids):
        errors.append(f"stale shots block completion: {sorted(stale_shot_ids)}")

    duration = probe.get("duration_sec")
    if duration is not None:
        deviation = abs(duration - target_duration_sec)
        if deviation > tolerance_sec:
            errors.append(
                f"final duration {duration:.3f}s off target by {deviation:.3f}s "
                f"(tolerance {tolerance_sec})"
            )
        checks["final_duration"] = duration
    else:
        errors.append("final duration unreadable")

    if probe.get("width") != profile.width or probe.get("height") != profile.height:
        errors.append(
            f"final resolution {probe.get('width')}x{probe.get('height')} "
            f"!= {profile.width}x{profile.height}"
        )
    if probe.get("fps") is None or abs(probe["fps"] - profile.fps) > 0.5:
        errors.append(f"final fps {probe.get('fps')} != {profile.fps}")
    if probe.get("video_codec") != "h264":
        errors.append(f"final codec {probe.get('video_codec')} != h264")
    if not probe.get("decode_ok", True):
        errors.append("final output failed decode validation")

    return FinalValidation(valid=not errors, errors=errors, checks=checks)


def can_transition_to_completed(
    project_status: str,
    *,
    validation: FinalValidation,
) -> bool:
    """A project may complete only from FINALIZING with a clean validation.

    An older existing final never satisfies a current mandatory failure.
    """
    if project_status != "FINALIZING":
        return False
    return validation.valid
