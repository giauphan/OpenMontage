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
    profile: MediaProfile,
    *,
    narration: Optional[str] = None,
    music: Optional[str] = None,
    sfx: Optional[str] = None,
    subtitles: Optional[str] = None,
    max_duration_sec: Optional[float] = None,
    burn_subtitles: bool = False,
    ducking_threshold_db: float = -20.0,
    ducking_ratio: float = 5.0,
    audio_fade_in_sec: Optional[float] = None,
    audio_fade_out_sec: Optional[float] = None,
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

    scale_filter = f"fps={profile.fps},scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if subtitles and burn_subtitles:
        # Proper escaping for FFmpeg subtitle filter: escape \, :, and '
        escaped_subs = subtitles.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        scale_filter += f",subtitles='{escaped_subs}'"

    argv += [
        "-c:v", profile.codec,
        "-crf", str(profile.crf),
        "-pix_fmt", profile.pixel_format,
        "-vf", scale_filter
    ]

    filter_complex = []

    if len(audio_inputs) > 0:
        # Proper ducking via sidechaincompress if both narration and music are present
        if narration and music:
            narration_idx = 1
            music_idx = 2

            # Narration is used for ducking sidechain and amix, so we must split it
            filter_complex.append(f"[{narration_idx}:a]asplit=2[narr1][narr2]")

            if sfx:
                # Merge music and SFX first, then duck
                sfx_idx = 3
                filter_complex.append(f"[{music_idx}:a][{sfx_idx}:a]amix=inputs=2:duration=longest[bgmix]")
                filter_complex.append(f"[bgmix][narr1]sidechaincompress=threshold={ducking_threshold_db}dB:ratio={ducking_ratio}:attack=100:release=1000[ducked]")
                filter_complex.append(f"[narr2][ducked]amix=inputs=2:duration=longest[aout_pre]")
            else:
                filter_complex.append(f"[{music_idx}:a][narr1]sidechaincompress=threshold={ducking_threshold_db}dB:ratio={ducking_ratio}:attack=100:release=1000[ducked]")
                filter_complex.append(f"[narr2][ducked]amix=inputs=2:duration=longest[aout_pre]")
        elif len(audio_inputs) > 1:
            amix_inputs = "".join(f"[{i+1}:a]" for i in range(len(audio_inputs)))
            filter_complex.append(f"{amix_inputs}amix=inputs={len(audio_inputs)}:duration=longest[aout_pre]")
        else:
            filter_complex.append("[1:a]anull[aout_pre]")

        # Apply fades if requested (requires max_duration_sec for fade out)
        fade_filters = []
        if audio_fade_in_sec:
            fade_filters.append(f"afade=t=in:st=0:d={audio_fade_in_sec}")
        if audio_fade_out_sec and max_duration_sec:
            start_fade_out = max(0.0, max_duration_sec - audio_fade_out_sec)
            fade_filters.append(f"afade=t=out:st={start_fade_out}:d={audio_fade_out_sec}")

        if fade_filters:
            filter_complex.append(f"[aout_pre]{','.join(fade_filters)}[aout]")
        else:
            filter_complex.append("[aout_pre]anull[aout]")

    if filter_complex:
         argv += ["-filter_complex", ";".join(filter_complex)]
         argv += ["-map", "0:v", "-map", "[aout]"]
    else:
        argv += ["-map", "0:v"]
        argv += ["-map", "0:a?"]

    if subtitles and not burn_subtitles:
        argv += ["-c:s", "mov_text", "-map", f"{len(audio_inputs)+1}:s"]

    if max_duration_sec is not None:
        argv += ["-t", str(max_duration_sec)]

    if audio_inputs or (subtitles and not burn_subtitles):
        argv += ["-c:a", "aac", "-ar", "48000"]
    else:
        # If no audio inputs, just copy base audio if present
        argv += ["-c:a", "copy"]

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
    ducking_threshold_db: float = -20.0,
    ducking_ratio: float = 5.0,
    audio_fade_in_sec: Optional[float] = None,
    audio_fade_out_sec: Optional[float] = None,
    timeout: float = 600.0,
    dry_run: bool = False,
) -> list[str]:
    """Master the final video. ``dry_run`` returns argv without executing."""
    import os
    import subprocess
    from lib.multishot_media import probe_clip

    # Actual ffprobe duration-derived bound to prevent unbounded audio
    if not dry_run:
        probe = probe_clip(base_video)
        base_dur = probe.get("duration_sec")
        if base_dur is None:
             raise MultishotValidationError(f"could not determine duration of base_video {base_video}")
        if max_duration_sec is None or max_duration_sec > base_dur:
             max_duration_sec = base_dur

    # Atomic publication
    import pathlib
    import uuid
    out_path = pathlib.Path(out)
    temp_out = str(out_path.with_name(f"{out_path.stem}_{uuid.uuid4().hex}{out_path.suffix}"))

    argv = build_audio_mux_args(
        base_video, temp_out, profile,
        narration=narration, music=music, sfx=sfx, subtitles=subtitles,
        max_duration_sec=max_duration_sec, burn_subtitles=burn_subtitles,
        ducking_threshold_db=ducking_threshold_db, ducking_ratio=ducking_ratio,
        audio_fade_in_sec=audio_fade_in_sec, audio_fade_out_sec=audio_fade_out_sec,
    )
    if dry_run:
        # Re-build for the real out path just for dry_run argv
        return build_audio_mux_args(
            base_video, out, profile,
            narration=narration, music=music, sfx=sfx, subtitles=subtitles,
            max_duration_sec=max_duration_sec, burn_subtitles=burn_subtitles,
            ducking_threshold_db=ducking_threshold_db, ducking_ratio=ducking_ratio,
            audio_fade_in_sec=audio_fade_in_sec, audio_fade_out_sec=audio_fade_out_sec,
        )

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            if os.path.exists(temp_out):
                os.remove(temp_out)
            raise MultishotValidationError(
                f"final master failed: {result.stderr[-400:]}"
            )

        # Verify encoded profile output unconditionally, as we always encode now
        out_probe = probe_clip(temp_out)

        # Additional checks based on prompt instructions
        duration = out_probe.get("duration_sec")
        if duration is None or duration <= 0 or not out_probe.get("decode_ok", True):
             if os.path.exists(temp_out):
                 os.remove(temp_out)
             raise MultishotValidationError(f"final master validation failed: invalid duration ({duration}) or decode failed")

        if out_probe.get("video_codec") != "h264" or out_probe.get("pixel_format") != profile.pixel_format or out_probe.get("width") != profile.width or out_probe.get("height") != profile.height:
            if os.path.exists(temp_out):
                os.remove(temp_out)
            raise MultishotValidationError(f"final master profile verification failed: codec={out_probe.get('video_codec')}, pix_fmt={out_probe.get('pixel_format')}, dim={out_probe.get('width')}x{out_probe.get('height')}")

        os.replace(temp_out, out)
    except subprocess.TimeoutExpired as exc:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise MultishotValidationError(f"final master timed out after {timeout}s: {exc}")
    except Exception as exc:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise

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
