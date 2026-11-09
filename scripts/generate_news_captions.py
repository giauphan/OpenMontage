#!/usr/bin/env python3
"""Create strict, audio-specific Vietnamese captions for daily news renders."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def get_asr_cache_key(audio_sha: str, locale: str, model_size: str = "small") -> str:
    key_src = f"{audio_sha}:{locale}:{model_size}:v1"
    return hashlib.sha256(key_src.encode("utf-8")).hexdigest()


def _resolve_asr_cache_dir(cache_dir: Path | str | None = None) -> Path:
    """Resolve ASR cache directory, falling back safely to /tmp if read-only."""
    if cache_dir is not None:
        return Path(cache_dir)
    env_dir = os.environ.get("OPENMONTAGE_CACHE_DIR")
    if env_dir:
        return Path(env_dir) / "asr"
    default_dir = REPO_ROOT / ".cache/asr"
    try:
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir
    except (OSError, PermissionError):
        from lib.audio.narration_orchestrator import _safe_user_tmp_dir
        return _safe_user_tmp_dir("asr")


def check_asr_cache(cache_key: str, cache_dir: Path | str | None = None) -> dict | None:
    cache_path = _resolve_asr_cache_dir(cache_dir) / f"{cache_key}.json"
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_asr_cache(cache_key: str, data: dict, cache_dir: Path | str | None = None) -> None:
    try:
        resolved_dir = _resolve_asr_cache_dir(cache_dir)
        resolved_dir.mkdir(parents=True, exist_ok=True)
        cache_path = resolved_dir / f"{cache_key}.json"
        tmp_path = resolved_dir / f"{cache_key}.tmp.json"
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except (OSError, PermissionError):
        # Gracefully handle sandbox or container read-only environments
        pass


def generate_captions(audio_path, output_dir, *, transcriber=None, converter=None, locale=None):
    """Transcribe this exact audio file and convert only measured ASR timings."""
    audio_path = Path(audio_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = (output_dir / "transcript.json").resolve()
    transcript_text_path = (output_dir / "transcript.txt").resolve()
    srt_path = (output_dir / "subtitles.srt").resolve()
    timings_path = (output_dir / "word_timestamps.json").resolve()

    for path_item in (transcript_path, transcript_text_path, srt_path, timings_path):
        if path_item.parent != output_dir:
            raise ValueError(f"Path traversal detected: {path_item}")

    if locale is None:
        try:
            from lib.artifact_paths import resolve_project_locale
            for candidate in (output_dir.parent.parent, output_dir.parent):
                if (candidate / "project.json").is_file():
                    locale = resolve_project_locale(candidate)
                    break
        except Exception:
            pass

    asr_language = "en" if locale and locale.startswith("en") else "vi"

    # Check ASR cache only when using the default production transcriber on an existing file
    use_cache = (transcriber is None) and audio_path.is_file()
    cache_key = None
    cached_transcript = None
    if use_cache:
        audio_bytes = audio_path.read_bytes()
        audio_sha = hashlib.sha256(audio_bytes).hexdigest()
        cache_key = get_asr_cache_key(audio_sha, locale=locale or asr_language, model_size="small")
        cached_transcript = check_asr_cache(cache_key)
        if not isinstance(cached_transcript, dict) or cached_transcript.get("timing_source") != "asr":
            cached_transcript = None

    if cached_transcript is not None:
        transcript = cached_transcript
    else:
        if transcriber is None:
            from tools.analysis.transcriber import Transcriber

            transcriber = Transcriber()
        if converter is None:
            converter = Path(__file__).with_name("generate_vn_subtitles.py")

        try:
            result = transcriber.execute({
                "input_path": str(audio_path),
                "model_size": "small",
                "language": asr_language,
                "diarize": False,
                "output_dir": str(output_dir),
                "local_files_only": True,
            })
        except Exception as exc:
            raise RuntimeError(
                f"Cached-only transcription failed for {audio_path}: {exc}. "
                "Ensure faster-whisper model 'small' is already cached on the render "
                "host; this pipeline will not download it."
            ) from exc
        if not result.success:
            raise RuntimeError(
                "Cached-only transcription failed for "
                f"{audio_path}: {result.error}. Ensure faster-whisper model 'small' "
                "is already cached on the render host; this pipeline will not download it."
            )
        transcript = result.data
        if use_cache and cache_key and isinstance(transcript, dict) and transcript.get("timing_source") == "asr":
            save_asr_cache(cache_key, transcript)
    if not isinstance(transcript, dict) or transcript.get("timing_source") != "asr":
        raise RuntimeError(f"Transcriber did not return ASR timings for {audio_path}")
    words = transcript.get("word_timestamps")
    if not isinstance(words, list) or not words:
        raise RuntimeError(f"ASR returned no word timings for {audio_path}")
    valid_languages = ("en", "en-US", "eng", "vi", "vi-VN", "vie")
    if transcript.get("language") not in valid_languages:
        raise RuntimeError(f"ASR did not identify supported speech language (got '{transcript.get('language')}') for {audio_path}")

    try:
        from scripts.generate_vn_subtitles import get_audio_duration
        audio_dur = get_audio_duration(audio_path)
    except Exception:
        audio_dur = None

    sanitized_words = []
    previous_end = 0.0
    for w in words:
        if not isinstance(w, dict) or not isinstance(w.get("word"), str) or not w["word"].strip():
            continue
        start = w.get("start")
        end = w.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        start = float(start)
        end = float(end)
        if audio_dur is not None and start >= audio_dur:
            continue
        if start < previous_end:
            start = previous_end
        if end <= start:
            end = start + 0.05
        if audio_dur is not None and end > audio_dur:
            end = audio_dur
            if end <= start:
                start = max(0.0, end - 0.05)
        start = round(start, 3)
        end = round(end, 3)
        if end > start and start >= previous_end:
            sanitized_words.append({"word": w["word"], "start": start, "end": end})
            previous_end = end

    if not sanitized_words:
        raise RuntimeError(f"ASR returned no valid word timings for {audio_path}")

    transcript["word_timestamps"] = sanitized_words
    words = sanitized_words

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(transcript, ensure_ascii=False, indent=2))
    with open(transcript_text_path, "w", encoding="utf-8") as f:
        f.write(" ".join(word["word"].strip() for word in words))

    if converter is None:
        converter = (Path(__file__).parent / "generate_vn_subtitles.py").resolve()
    else:
        converter = Path(converter).resolve()

    command = [
        sys.executable, str(converter), str(transcript_text_path), str(audio_path),
        str(srt_path), "--output-json", str(timings_path),
        "--transcript-json", str(transcript_path), "--require-aligned",
        "--no-script-comparison",
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(
            f"Strict caption conversion failed for {audio_path} (exit {completed.returncode})"
        )
    return {"transcript": transcript_path, "srt": srt_path, "timings": timings_path}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--locale", default=None, help="Target project locale")
    args = parser.parse_args(argv)
    try:
        result = generate_captions(args.audio, args.output_dir, locale=args.locale)
        print(f"Generated aligned captions: {result['srt']}")
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"Caption generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
