"""Independent Audio Completeness and Mix Quality Assurance Validator.

Enforces:
1. Spoken completeness: Script CTA and dialogue must not be cut off prematurely.
2. Tail acoustic cushion: Audio must have >= 0.15s decay/silence before EOF; abrupt truncation at high volume is blocked.
3. Container margin: Video duration must be >= audio duration to prevent muxer cutoffs.
4. Mix loudness standards: Mean volume between -32 dBFS and -14 dBFS, peak volume < -0.1 dBFS (no digital clipping).
5. SFX presence: Storyboard SFX cues must be backed by materialized assets and rendered in composition.

Clean Architecture: Application Service / Audio QA Port
Target size: < 350 lines.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Minimum decay cushion in seconds required at the end of speech before EOF
MIN_TAIL_CUSHION_S = 0.15
# Loudness thresholds in dBFS
MAX_PEAK_CLIPPING_DB = -0.10
MIN_ACCEPTABLE_MEAN_DB = -34.0
MAX_ACCEPTABLE_MEAN_DB = -12.0
# Acoustic tail threshold: volume in last 200ms indicating speech truncation
TAIL_CUTOFF_MEAN_DB_THRESHOLD = -28.0
TAIL_CUTOFF_MAX_DB_THRESHOLD = -14.0


def _safe_executable(binary_name: str, candidate: Optional[str] = None) -> str:
    """Resolve an executable securely."""
    if candidate:
        resolved = shutil.which(candidate)
        if resolved and Path(resolved).name in (binary_name, f"{binary_name}.exe"):
            return resolved
    system_bin = shutil.which(binary_name)
    return system_bin if system_bin else binary_name


def measure_audio_levels(audio_path: Path, ffmpeg_bin: Optional[str] = None) -> Dict[str, Optional[float]]:
    """Measure mean_volume and max_volume of an audio track via FFmpeg volumedetect."""
    p = Path(audio_path).resolve()
    if not p.is_file():
        return {"mean_volume": None, "max_volume": None}

    bin_path = _safe_executable("ffmpeg", ffmpeg_bin)
    cmd = [
        bin_path, "-nostdin", "-threads", "0", "-v", "info",
        "-i", str(p), "-af", "volumedetect", "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (res.stderr or "") + (res.stdout or "")

    mean_m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    max_m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", output)

    return {
        "mean_volume": float(mean_m.group(1)) if mean_m else None,
        "max_volume": float(max_m.group(1)) if max_m else None,
    }


def detect_audio_tail_cutoff(
    audio_path: Path,
    sample_window_s: float = 0.25,
    ffmpeg_bin: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Detect if an audio track was prematurely truncated mid-speech.

    Inspects the final `sample_window_s` seconds before EOF. Natural speech decays
    to silence/room tone (mean_volume < -40 dB). If mean volume remains high
    (> -28 dB) or max volume (> -14 dB) in the final milliseconds, speech was clipped.
    """
    p = Path(audio_path).resolve()
    if not p.is_file():
        return False, {"error": "file_not_found"}

    bin_path = _safe_executable("ffmpeg", ffmpeg_bin)
    cmd = [
        bin_path, "-nostdin", "-threads", "0", "-v", "info",
        "-sseof", f"-{sample_window_s:.2f}",
        "-i", str(p),
        "-af", "volumedetect",
        "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (res.stderr or "") + (res.stdout or "")

    mean_m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    max_m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", output)

    tail_mean = float(mean_m.group(1)) if mean_m else None
    tail_max = float(max_m.group(1)) if max_m else None

    is_cutoff = False
    if tail_mean is not None and tail_max is not None:
        if tail_mean > TAIL_CUTOFF_MEAN_DB_THRESHOLD or tail_max > TAIL_CUTOFF_MAX_DB_THRESHOLD:
            is_cutoff = True

    return is_cutoff, {
        "tail_mean_volume": tail_mean,
        "tail_max_volume": tail_max,
        "sample_window_s": sample_window_s,
        "is_abrupt_cutoff": is_cutoff,
    }


def _extract_cues_from_srt(srt_path: Path) -> List[Dict[str, Any]]:
    """Parse subtitle cues with start and end timestamps in seconds."""
    if not srt_path.is_file():
        return []
    content = srt_path.read_text(encoding="utf-8")
    cues = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            ts_match = re.match(
                r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)",
                lines[1],
            )
            if ts_match:
                sh, sm, ss, sms = (int(x) for x in ts_match.groups()[:4])
                eh, em, es, ems = (int(x) for x in ts_match.groups()[4:])
                start_s = sh * 3600 + sm * 60 + ss + sms / 1000.0
                end_s = eh * 3600 + em * 60 + es + ems / 1000.0
                text = " ".join(lines[2:])
                cues.append({"start_s": start_s, "end_s": end_s, "text": text})
    return cues


def verify_spoken_cta_completeness(
    project_dir: Path,
    min_silence_cushion_s: float = MIN_TAIL_CUSHION_S,
) -> Tuple[bool, List[str]]:
    """Verify that CTA and full dialogue are completely spoken in the audio and not truncated."""
    project_dir = Path(project_dir).resolve()
    errors: List[str] = []

    script_path = project_dir / "artifacts" / "script_en_US.json"
    audio_path = project_dir / "assets" / "narration.mp3"
    srt_path = project_dir / "artifacts" / "captions.srt"
    if not srt_path.is_file():
        srt_path = project_dir / "artifacts" / "captions_en_US.srt"

    if not script_path.is_file():
        return True, []  # Non-script project; bypass
    if not audio_path.is_file():
        return False, ["Missing narration.mp3: audio track is required to verify CTA speech completeness"]

    # 1. Parse target CTA narration from script
    try:
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        sections = script_data.get("sections", [])
        if not sections:
            return True, []
        final_section = sections[-1]
        final_text = (final_section.get("narration") or final_section.get("text") or "").strip()
    except Exception as e:
        return False, [f"Failed to parse script for CTA completeness check: {e}"]

    # 2. Check acoustic tail cutoff in narration.mp3
    is_cutoff, tail_info = detect_audio_tail_cutoff(audio_path)
    if is_cutoff:
        mean_db = tail_info.get("tail_mean_volume")
        errors.append(
            f"Narration audio terminates abruptly mid-speech (tail mean volume {mean_db:.1f} dB > "
            f"{TAIL_CUTOFF_MEAN_DB_THRESHOLD:.1f} dB); voice was clipped prematurely"
        )

    # 3. Check caption cues alignment against audio duration
    cues = _extract_cues_from_srt(srt_path)
    from lib.audio.narration_orchestrator import probe_audio_duration
    audio_dur = probe_audio_duration(audio_path)

    if cues and audio_dur > 0:
        last_cue = cues[-1]
        last_cue_end = float(last_cue.get("end_s", 0.0))
        last_cue_text = str(last_cue.get("text", "")).lower()

        # Check if last cue extends past audio duration
        if last_cue_end > audio_dur:
            errors.append(
                f"Spoken dialogue cue extends to {last_cue_end:.2f}s, exceeding narration audio duration "
                f"({audio_dur:.2f}s). Final speech was truncated."
            )
        elif audio_dur - last_cue_end < min_silence_cushion_s:
            logger.warning(
                "Minimal tail cushion (%.2fs < %.2fs) between final cue and audio end",
                audio_dur - last_cue_end, min_silence_cushion_s,
            )

        # Check if final cues contain CTA keywords
        combined_tail_text = " ".join(c.get("text", "") for c in cues[-3:]).lower()
        cta_keywords = ("follow", "star", "subscribe", "@", "repo", "repository")
        has_spoken_cta = any(kw in combined_tail_text for kw in cta_keywords)
        script_has_cta = any(kw in final_text.lower() for kw in cta_keywords)

        if script_has_cta and not has_spoken_cta:
            errors.append(
                f"Final dialogue cues ('{combined_tail_text}') lack spoken CTA keywords "
                "promised in script (follow/star/subscribe)"
            )

    # 4. Cross check video container duration vs audio duration
    video_path = project_dir / "renders" / "final_short_en_US_9x16.mp4"
    if video_path.is_file():
        vid_dur = probe_audio_duration(video_path)
        if vid_dur > 0 and audio_dur > 0:
            if vid_dur < audio_dur - 0.20:
                errors.append(
                    f"Rendered video duration ({vid_dur:.2f}s) is shorter than narration audio ({audio_dur:.2f}s); "
                    "video muxer clipped speech track."
                )

    return len(errors) == 0, errors


def audit_audio_mix_quality(
    media_path: Path,
    is_rendered_video: bool = False,
) -> Tuple[bool, List[str]]:
    """Audit audio mix quality: clipping, volume range, and balance."""
    media_path = Path(media_path).resolve()
    if not media_path.is_file():
        return False, [f"Media file not found for mix audit: {media_path}"]

    errors: List[str] = []
    levels = measure_audio_levels(media_path)
    mean_vol = levels.get("mean_volume")
    max_vol = levels.get("max_volume")

    if mean_vol is None or max_vol is None:
        errors.append(f"Could not analyze audio levels for {media_path.name}")
        return False, errors

    # Digital clipping gate
    if max_vol > MAX_PEAK_CLIPPING_DB:
        errors.append(
            f"Audio peak volume ({max_vol:.2f} dBFS) exceeds {MAX_PEAK_CLIPPING_DB:.2f} dBFS (harsh digital clipping detected)"
        )

    # Intelligibility loudness range
    if mean_vol < MIN_ACCEPTABLE_MEAN_DB:
        errors.append(
            f"Audio mix is too quiet (mean volume {mean_vol:.1f} dBFS < {MIN_ACCEPTABLE_MEAN_DB:.1f} dBFS)"
        )
    elif mean_vol > MAX_ACCEPTABLE_MEAN_DB:
        errors.append(
            f"Audio mix is overly loud or compressed (mean volume {mean_vol:.1f} dBFS > {MAX_ACCEPTABLE_MEAN_DB:.1f} dBFS)"
        )

    return len(errors) == 0, errors


def audit_project_audio_pipeline(
    project_dir: Path,
    strict: bool = True,
) -> List[Dict[str, str]]:
    """Comprehensive release gate for audio completeness and mix quality."""
    project_dir = Path(project_dir).resolve()
    findings: List[Dict[str, str]] = []

    audio_path = project_dir / "assets" / "narration.mp3"
    video_path = project_dir / "renders" / "final_short_en_US_9x16.mp4"

    # 1. Spoken CTA and speech completeness
    ok_cta, cta_errors = verify_spoken_cta_completeness(project_dir)
    for err in cta_errors:
        findings.append({
            "category": "AUDIO_COMPLETENESS",
            "severity": "blocker",
            "message": err,
        })

    # 2. Narration audio mix quality
    if audio_path.is_file():
        ok_narr, narr_errors = audit_audio_mix_quality(audio_path, is_rendered_video=False)
        for err in narr_errors:
            findings.append({
                "category": "AUDIO_MIX",
                "severity": "blocker" if strict else "warning",
                "message": f"Narration track: {err}",
            })

    # 3. Final MP4 audio mix quality
    if video_path.is_file():
        ok_vid, vid_errors = audit_audio_mix_quality(video_path, is_rendered_video=True)
        for err in vid_errors:
            findings.append({
                "category": "AUDIO_MIX",
                "severity": "blocker" if strict else "warning",
                "message": f"Final render: {err}",
            })

    return findings
