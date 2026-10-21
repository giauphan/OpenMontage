#!/usr/bin/env python3
"""Create strict, audio-specific Vietnamese captions for daily news renders."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def generate_captions(audio_path, output_dir, *, transcriber=None, converter=None, locale=None):
    """Transcribe this exact audio file and convert only measured ASR timings."""
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "transcript.json"
    transcript_text_path = output_dir / "transcript.txt"
    srt_path = output_dir / "subtitles.srt"
    timings_path = output_dir / "word_timestamps.json"

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

    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript_text_path.write_text(" ".join(word["word"].strip() for word in words), encoding="utf-8")
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
