"""Unit tests for lib.fixed_niche.captions module."""
from __future__ import annotations

from pathlib import Path
import pytest

from lib.fixed_niche.captions import (
    format_srt_timestamp,
    format_ass_timestamp,
    chunk_text_by_clauses,
    generate_cues_from_beats,
    generate_cues_from_words,
    generate_captions_srt,
    generate_captions_ass,
    build_and_align_captions,
)


def test_srt_and_ass_timestamp_formatting():
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(65.432) == "00:01:05,432"
    assert format_srt_timestamp(-5.0) == "00:00:00,000"

    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(65.432) == "0:01:05.43"
    assert format_ass_timestamp(3661.05) == "1:01:01.05"


def test_chunk_text_by_clauses_splits_long_sentence():
    long_sentence = (
        "The root cause is ephemeral session memory. "
        "Large language models maintain zero persistent state across process restarts "
        "unless repository instructions are explicitly injected into the agent system prompt on every invocation."
    )
    chunks = chunk_text_by_clauses(long_sentence, max_words=5, max_chars=34)
    assert len(chunks) >= 5
    for c in chunks:
        words = c.split()
        assert len(words) <= 6
        assert len(c) <= 45


def test_generate_cues_from_beats_monotonic():
    beats = [
        {"beat_id": "B01", "start_s": 0.0, "end_s": 5.0, "narration": "Why do coding agents lose requirements?"},
        {"beat_id": "B02", "start_s": 5.0, "end_s": 15.0, "narration": "The root cause is ephemeral memory across process restarts."},
    ]
    cues = generate_cues_from_beats(beats, max_words=4)
    assert len(cues) >= 4
    prev_end = 0.0
    for cue in cues:
        assert cue["start_s"] >= prev_end - 0.001
        assert cue["end_s"] > cue["start_s"]
        prev_end = cue["end_s"]
    assert cues[0]["start_s"] == 0.0
    assert pytest.approx(cues[-1]["end_s"], 0.01) == 15.0


def test_generate_cues_from_words_handles_pauses_and_punctuation():
    words = [
        {"word": "Why", "start": 0.0, "end": 0.3},
        {"word": "does", "start": 0.3, "end": 0.5},
        {"word": "memory", "start": 0.5, "end": 0.9},
        {"word": "reset?", "start": 0.9, "end": 1.4},
        # Gap of 0.8s
        {"word": "Because", "start": 2.2, "end": 2.6},
        {"word": "sessions", "start": 2.6, "end": 3.0},
        {"word": "are", "start": 3.0, "end": 3.2},
        {"word": "ephemeral.", "start": 3.2, "end": 3.8},
    ]
    cues = generate_cues_from_words(words, max_words=4, max_pause_s=0.5)
    assert len(cues) == 2
    assert cues[0]["text"] == "Why does memory reset?"
    assert cues[1]["text"] == "Because sessions are ephemeral."
    assert cues[0]["start_s"] == 0.0
    assert cues[1]["start_s"] == 2.2


def test_generate_captions_srt_and_ass_output():
    cues = [
        {"number": 1, "start_s": 0.0, "end_s": 2.5, "text": "First phrase cue"},
        {"number": 2, "start_s": 2.5, "end_s": 5.0, "text": "Second phrase cue"},
    ]
    srt = generate_captions_srt(cues)
    assert "1\n00:00:00,000 --> 00:00:02,500\nFirst phrase cue" in srt
    assert "2\n00:00:02,500 --> 00:00:05,000\nSecond phrase cue" in srt

    ass = generate_captions_ass(cues, width=1080, height=1920, margin_v=240)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "MarginV, Encoding" in ass
    assert ",240,1" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,First phrase cue" in ass


def test_build_and_align_captions_fallback(tmp_path: Path):
    beats = [
        {"beat_id": "B01", "start_s": 0.0, "end_s": 6.0, "narration": "Why does your agent forget instructions between sessions?"},
    ]
    srt, ass, cues = build_and_align_captions(beats, audio_path=None)
    assert len(cues) >= 2
    assert "-->" in srt
    assert "PlayResX: 1080" in ass
