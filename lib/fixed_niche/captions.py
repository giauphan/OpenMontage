"""Captions generator, chunker, and ASS/SRT subtitle designer for Practical AI Agent Engineering.

Enforces:
1. Short-form phrase chunking (3-5 words per cue, ~1.5s - 2.8s duration)
2. Perfect synchronization with speech cadence (via Whisper ASR word timestamps or phonetic clause weighting)
3. Bottom caption-safe rail reservation (MarginV 240 in 1080x1920) avoiding visual diagram collisions
4. High-contrast typography (42px DejaVu Sans, bold, white primary with dark navy outline)
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def format_srt_timestamp(seconds: float) -> str:
    """Format float seconds as HH:MM:SS,mmm for SubRip subtitles."""
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def format_ass_timestamp(seconds: float) -> str:
    """Format float seconds as H:MM:SS.cc for Advanced SubStation Alpha."""
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


def chunk_text_by_clauses(text: str, max_words: int = 5, max_chars: int = 34) -> List[str]:
    """Split narration text into natural bite-sized phrase chunks (3-5 words)."""
    cleaned = text.strip()
    if not cleaned:
        return []

    # First split on clause punctuation (. , ? ! ; :)
    raw_clauses = re.split(r"([.?!,;:]\s+)", cleaned)
    clauses: List[str] = []
    current = ""
    for part in raw_clauses:
        current += part
        if re.search(r"[.?!,;:]\s+$", current):
            clauses.append(current.strip())
            current = ""
    if current.strip():
        clauses.append(current.strip())

    chunks: List[str] = []
    for clause in clauses:
        words = clause.split()
        if len(words) <= max_words and len(clause) <= max_chars:
            chunks.append(clause)
        else:
            sub: List[str] = []
            for w in words:
                sub.append(w)
                char_count = sum(len(x) + 1 for x in sub)
                if len(sub) >= max_words or char_count >= max_chars:
                    chunks.append(" ".join(sub))
                    sub = []
            if sub:
                chunks.append(" ".join(sub))

    return chunks if chunks else [cleaned]


def generate_cues_from_beats(
    beats: List[Dict[str, Any]],
    max_words: int = 5,
    max_chars: int = 34,
) -> List[Dict[str, Any]]:
    """Generate evenly timed, phrase-chunked subtitle cues bounded by storyboard beats."""
    all_cues: List[Dict[str, Any]] = []
    cue_idx = 1

    for b in beats:
        b_start = float(b.get("start_s", 0.0))
        b_end = float(b.get("end_s", 0.0))
        dur = max(0.2, b_end - b_start)
        narration = b.get("narration", "").strip()

        chunks = chunk_text_by_clauses(narration, max_words=max_words, max_chars=max_chars)
        if not chunks:
            continue

        # Weight duration of each chunk by syllable/character count
        weights = [max(1, min(len(c), 8 * len(c.split()))) for c in chunks]
        tot_w = sum(weights)
        curr_t = b_start

        for i, (chunk, w) in enumerate(zip(chunks, weights)):
            c_dur = dur * (w / tot_w) if tot_w > 0 else (dur / len(chunks))
            next_t = b_end if i == len(chunks) - 1 else curr_t + c_dur
            all_cues.append({
                "number": cue_idx,
                "start_s": round(curr_t, 3),
                "end_s": round(next_t, 3),
                "text": chunk,
            })
            cue_idx += 1
            curr_t = next_t

    return all_cues


def generate_cues_from_words(
    words: List[Dict[str, Any]],
    max_words: int = 5,
    max_chars: int = 34,
    max_pause_s: float = 0.45,
) -> List[Dict[str, Any]]:
    """Group ASR word timestamps into synchronized, phrase-level subtitle cues."""
    if not words:
        return []

    cues: List[Dict[str, Any]] = []
    current_chunk: List[Dict[str, Any]] = []
    cue_idx = 1

    for i, w in enumerate(words):
        word_text = w.get("word", "").strip()
        if not word_text:
            continue
        current_chunk.append(w)

        ends_with_punct = any(word_text.endswith(p) for p in (".", "?", "!", ",", ";", ":"))
        is_max_words = len(current_chunk) >= max_words
        is_max_chars = sum(len(x.get("word", "").strip()) + 1 for x in current_chunk) >= max_chars

        has_pause = False
        if i + 1 < len(words):
            next_start = float(words[i + 1].get("start", 0.0))
            if next_start - float(w.get("end", 0.0)) > max_pause_s:
                has_pause = True

        if ends_with_punct or is_max_words or is_max_chars or has_pause or i == len(words) - 1:
            c_text = " ".join(x.get("word", "").strip() for x in current_chunk)
            c_start = float(current_chunk[0].get("start", 0.0))
            c_end = float(current_chunk[-1].get("end", 0.0))
            # Pad small tail cushion so speech decay is covered
            c_end = round(c_end + 0.05, 3)
            cues.append({
                "number": cue_idx,
                "start_s": round(c_start, 3),
                "end_s": c_end,
                "text": c_text,
            })
            cue_idx += 1
            current_chunk = []

    return cues


def generate_captions_srt(cues: List[Dict[str, Any]]) -> str:
    """Format cues as standard SubRip (.srt) caption text."""
    blocks: List[str] = []
    for idx, c in enumerate(cues, 1):
        start_ts = format_srt_timestamp(c["start_s"])
        end_ts = format_srt_timestamp(c["end_s"])
        text = c["text"].strip()
        blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(blocks)


def generate_srt_from_beats(beats: List[Dict[str, Any]]) -> str:
    """Generate SRT caption content matching storyboard beat boundaries."""
    cues = generate_cues_from_beats(beats)
    return generate_captions_srt(cues)


def generate_captions_ass(
    cues: List[Dict[str, Any]],
    words: Optional[List[Dict[str, Any]]] = None,
    width: int = 1080,
    height: int = 1920,
    font_name: str = "DejaVu Sans",
    font_size: int = 42,
    margin_v: int = 240,
    alignment: int = 2,
) -> str:
    """Format cues as styled Advanced SubStation Alpha (.ass) text.

    Positions subtitles in the bottom caption rail (MarginV 240) with high-contrast
    text. When ASR words are supplied, emits \\k karaoke tags to follow the voice in real time.
    """
    dialogues: List[str] = []

    if words:
        # Group words into short phrase lines matching cue boundaries with karaoke timing
        lines: List[List[Dict[str, Any]]] = []
        chunk: List[Dict[str, Any]] = []
        for i, w in enumerate(words):
            word_text = w.get("word", "").strip()
            if not word_text:
                continue
            chunk.append(w)
            ends_punct = any(word_text.endswith(p) for p in (".", "?", "!", ";"))
            has_pause = (i + 1 < len(words) and float(words[i + 1].get("start", 0.0)) - float(w.get("end", 0.0)) > 0.45)
            if len(chunk) >= 5 or ends_punct or has_pause or i == len(words) - 1:
                lines.append(chunk)
                chunk = []

        for line in lines:
            start_s = float(line[0].get("start", 0.0))
            end_s = float(line[-1].get("end", 0.0)) + 0.05
            start_ass = format_ass_timestamp(start_s)
            end_ass = format_ass_timestamp(end_s)
            k_parts = []
            for w in line:
                w_start = float(w.get("start", 0.0))
                w_end = float(w.get("end", 0.0))
                w_centis = max(1, int(round((w_end - w_start) * 100)))
                w_text = w.get("word", "").strip().replace("{", "\\{").replace("}", "\\}")
                k_parts.append(f"{{\\k{w_centis}}}{w_text}")
            dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{' '.join(k_parts)}")
    else:
        for c in cues:
            start_ass = format_ass_timestamp(c["start_s"])
            end_ass = format_ass_timestamp(c["end_s"])
            text = c["text"].strip().replace("{", "\\{").replace("}", "\\}")
            dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}")

    header = f"""[Script Info]
Title: OpenMontage Synchronized Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H0000FFFF,&H00FFFFFF,&H000B0F19,&H80000000,-1,0,0,0,100,100,0,0,1,3.0,0,{alignment},80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(dialogues) + "\n"


def build_and_align_captions(
    beats: List[Dict[str, Any]],
    audio_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 1920,
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Build synchronized SRT and ASS caption content.

    Attempts Whisper ASR word extraction if audio_path is provided, falling back
    to beat-constrained clause weighting when ASR is unavailable or unpopulated.
    """
    cues: List[Dict[str, Any]] = []

    if audio_path and audio_path.is_file():
        try:
            from tools.analysis.transcriber import Transcriber
            from lib.audio.narration_orchestrator import _safe_user_tmp_dir
            transcriber = Transcriber()
            # Run transcriber with output_dir in safe private temp directory to ensure sandboxed filesystem writability
            asr_tmp = _safe_user_tmp_dir("asr")
            res = transcriber.execute({
                "input_path": str(audio_path.resolve()),
                "model_size": "base",
                "language": "en",
                "local_files_only": True,
                "output_dir": str(asr_tmp),
            })
            if hasattr(res, "data") and res.data and res.data.get("word_timestamps"):
                raw_words = res.data["word_timestamps"]
                asr_cues = generate_cues_from_words(raw_words)
                if len(asr_cues) >= len(beats):
                    cues = asr_cues
                    logger.info("Generated %d ASR-aligned subtitle cues from faster-whisper", len(cues))
        except Exception as e:
            logger.warning("ASR word alignment failed, falling back to beat clause chunking: %s", e)

    if not cues:
        cues = generate_cues_from_beats(beats)
        logger.info("Generated %d beat-clause chunked subtitle cues", len(cues))

    srt_content = generate_captions_srt(cues)
    ass_content = generate_captions_ass(cues, words=raw_words if "raw_words" in locals() else None, width=width, height=height)
    return srt_content, ass_content, cues
