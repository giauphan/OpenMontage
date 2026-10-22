#!/usr/bin/env python3
"""Generate Vietnamese SRT subtitles from estimated or ASR word timings."""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


def normalize_words(text):
    """Conservative Unicode normalization for script/transcript comparison."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(char for char in token if char.isalnum())
                    for token in normalized.split() if any(char.isalnum() for char in token))


def _validate_limits(max_words, max_duration):
    if isinstance(max_words, bool) or not isinstance(max_words, int) or max_words < 1:
        raise ValueError("max_words must be a positive integer")
    if not isinstance(max_duration, (int, float)) or not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("max_duration must be finite and positive")


def estimate_subtitles(text, audio_duration, max_words=3, max_duration=4.0):
    """Return evenly distributed estimates, bounded by the measured duration."""
    _validate_limits(max_words, max_duration)
    words = text.strip().split()
    if not words or not math.isfinite(audio_duration) or audio_duration <= 0:
        return [], []

    weights = [max(1, min(len(word), 8)) for word in words]
    total_weight = sum(weights)
    times = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        end = audio_duration if len(times) == len(words) - 1 else cursor + audio_duration * weight / total_weight
        times.append({"word": word, "start": cursor, "end": end})
        cursor = end

    cues = []
    batch = []
    for entry in times:
        if batch and (len(batch) >= max_words or entry["end"] - batch[0]["start"] > max_duration):
            cues.append(_cue(batch, len(cues) + 1))
            batch = []
        batch.append(entry)
    if batch:
        cues.append(_cue(batch, len(cues) + 1))
    return cues, times


def _cue(entries, number):
    return {"number": number, "start": entries[0]["start"], "end": entries[-1]["end"],
            "text": " ".join(item["word"] for item in entries)}


def aligned_subtitles(transcript, audio_hash, duration, max_words=3, max_duration=4.0):
    _validate_limits(max_words, max_duration)
    if not isinstance(transcript, dict) or transcript.get("timing_source") != "asr":
        raise ValueError("transcript JSON must declare timing_source='asr'")
    if transcript.get("audio_sha256") != audio_hash:
        raise ValueError("transcript audio_sha256 does not match input audio")
    valid_languages = ("en", "en-US", "eng", "vi", "vi-VN", "vie")
    if transcript.get("language") not in valid_languages:
        raise ValueError(f"transcript language '{transcript.get('language')}' not supported")
    words = transcript.get("word_timestamps")
    if not isinstance(words, list) or not words:
        raise ValueError("transcript has no word_timestamps")
    parsed = []
    previous_end = -1.0
    for item in words:
        if not isinstance(item, dict) or not isinstance(item.get("word"), str) or not item["word"].strip():
            raise ValueError("invalid or empty transcript word")
        start, end = item.get("start"), item.get("end")
        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or
                not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end) or
                start < 0 or end <= start or end > duration or start < previous_end):
            raise ValueError("word timings must be finite, chronological, non-overlapping, and within audio duration")
        parsed.append({"word": item["word"], "start": start, "end": end})
        previous_end = end
    cues = []
    batch = []
    for word in parsed:
        if batch and (len(batch) >= max_words or word["end"] - batch[0]["start"] > max_duration):
            cues.append(_cue(batch, len(cues) + 1))
            batch = []
        batch.append(word)
    if batch:
        cues.append(_cue(batch, len(cues) + 1))
    return cues, parsed


def format_srt(cues):
    def stamp(seconds):
        # Round once to integer milliseconds, carrying across second boundaries.
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds_part, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds:03d}"

    return "".join(f"{cue['number']}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}\n\n" for cue in cues)


def get_audio_duration(audio_path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", str(audio_path)], capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise ValueError("ffprobe could not determine audio duration")
    try:
        duration = float(result.stdout.strip())
    except (TypeError, ValueError):
        raise ValueError("ffprobe returned an invalid audio duration")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("ffprobe returned a non-positive audio duration")
    return duration


def _atomic_outputs(outputs):
    staged = []
    try:
        for target, content in outputs:
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            staged.append((Path(temp_name), target))
        for temp, target in staged:
            os.replace(temp, target)
    finally:
        for temp, _ in staged:
            if temp.exists():
                temp.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_path", type=Path)
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("output_srt", type=Path)
    parser.add_argument("legacy_output_json", nargs="?")
    parser.add_argument("legacy_max_words", nargs="?", type=int)
    parser.add_argument("--output-json", dest="output_json")
    parser.add_argument("--transcript-json", type=Path)
    parser.add_argument("--require-aligned", action="store_true")
    parser.add_argument(
        "--no-script-comparison",
        action="store_true",
        help="Mark script comparison unavailable when the input text is ASR-derived",
    )
    parser.add_argument("--max-words", type=int)
    args = parser.parse_args(argv)
    try:
        max_words = args.max_words if args.max_words is not None else (args.legacy_max_words if args.legacy_max_words is not None else 3)
        _validate_limits(max_words, 4.0)
        output_json = args.output_json or args.legacy_output_json
        input_paths = [args.text_path, args.audio_path]
        if args.transcript_json:
            input_paths.append(args.transcript_json)
        output_paths = [args.output_srt] + ([Path(output_json), Path(output_json).parent / "narration_words.js"] if output_json else [])
        input_resolved = {path.resolve() for path in input_paths}
        if any(path.resolve() in input_resolved for path in output_paths) or len({path.resolve() for path in output_paths}) != len(output_paths):
            raise ValueError("output paths must be distinct from each other and all input paths")
        if args.require_aligned and not args.transcript_json:
            raise ValueError("--require-aligned requires --transcript-json")
        text = args.text_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Empty text file")
        audio_hash = hashlib.sha256(args.audio_path.read_bytes()).hexdigest()
        duration = get_audio_duration(args.audio_path)
        if args.transcript_json:
            transcript = json.loads(args.transcript_json.read_text(encoding="utf-8"))
            cues, timestamps = aligned_subtitles(transcript, audio_hash, duration, max_words)
            timing_source = "asr"
        else:
            cues, timestamps = estimate_subtitles(text, duration, max_words)
            timing_source = "estimated"
        data = {"word_timestamps": timestamps, "duration_seconds": round(duration, 3),
                "language": "vi-VN", "audio_sha256": audio_hash,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "script_matches_transcript": (None if args.no_script_comparison else
                    normalize_words(text) == normalize_words(" ".join(word["word"] for word in timestamps))),
                "script_comparison_available": not args.no_script_comparison,
                "timing_source": timing_source, "timing_verified": False}
        outputs = [(args.output_srt, format_srt(cues))]
        if output_json:
            outputs.extend([(output_json, json.dumps(data, indent=2, ensure_ascii=False)),
                            (Path(output_json).parent / "narration_words.js",
                             f"window.__narrationWords = {json.dumps(timestamps, ensure_ascii=False)};\n")])
        _atomic_outputs(outputs)
        print(f"Generated {len(cues)} subtitle cues ({timing_source})")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
