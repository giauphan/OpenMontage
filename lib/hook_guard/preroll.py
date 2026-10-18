"""Extractive pre-roll generation, boundary verification, and EDL mutation for HookGuard."""

from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from lib.hook_guard.canonical_edl import (
    compute_body_edl_fingerprint,
    verify_body_edl_preservation,
)
from lib.hook_guard.config import HookPolicy


def verify_preroll_boundaries(
    source_in: float,
    source_out: float,
    transcript_words: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, dict[str, bool]]:
    """Check word and sentence boundary integrity for an extractive pre-roll segment.
    
    Returns (is_valid, boundary_flags).
    """
    flags = {
        "mid_word_cut": False,
        "mid_sentence_cut": False,
    }

    if not transcript_words:
        # Without word-level timestamps, assume conservative validity
        return True, flags

    # Check if source_in falls in the middle of a spoken word
    for w in transcript_words:
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", 0.0))
        # If in_seconds is strictly inside a word's duration (with 0.05s tolerance)
        if (w_start + 0.05) < source_in < (w_end - 0.05):
            flags["mid_word_cut"] = True
            break
        if (w_start + 0.05) < source_out < (w_end - 0.05):
            flags["mid_word_cut"] = True
            break

    # Check sentence boundary at end: word at or right before source_out
    words_before_end = [w for w in transcript_words if float(w.get("end", 0.0)) <= source_out + 0.15]
    if words_before_end:
        last_word = words_before_end[-1].get("word", "")
        # If last word doesn't end with sentence-ending punctuation and next word is immediate:
        if not any(last_word.endswith(punct) for punct in [".", "!", "?", "..."]):
            words_after_end = [w for w in transcript_words if float(w.get("start", 0.0)) >= source_out - 0.1]
            if words_after_end and (float(words_after_end[0].get("start", 0.0)) - float(words_before_end[-1].get("end", 0.0)) < 0.25):
                flags["mid_sentence_cut"] = True

    is_valid = not (flags["mid_word_cut"] or flags["mid_sentence_cut"])
    return is_valid, flags


def apply_extractive_preroll(
    edl: dict[str, Any],
    preroll_span: dict[str, Any],
    source_id: str = "main",
    policy: Optional[HookPolicy] = None,
) -> tuple[dict[str, Any], float]:
    """Inject an extractive pre-roll cut into the EDL.
    
    Invariants:
      1. Tagged pre-roll cut is inserted at index 0 with is_hook_preroll: True.
      2. The original source occurrence in the body cuts is retained intact.
      3. Global audio schedule is shifted by added_duration so body-relative timing is preserved.
      4. No overlapping transition at pre-roll boundary.
      
    Returns (mutated_edl, added_duration).
    """
    mutated = copy.deepcopy(edl)
    src_in = float(preroll_span["source_in_seconds"])
    src_out = float(preroll_span["source_out_seconds"])
    added_duration = max(0.0, src_out - src_in)

    if policy and added_duration > policy.max_added_duration_seconds:
        raise ValueError(
            f"Pre-roll duration {added_duration:.2f}s exceeds policy limit {policy.max_added_duration_seconds:.2f}s"
        )

    preroll_cut_id = f"hook_preroll_{uuid.uuid4().hex[:8]}"
    preroll_cut = {
        "id": preroll_cut_id,
        "source": source_id,
        "in_seconds": round(src_in, 3),
        "out_seconds": round(src_out, 3),
        "speed": 1.0,
        "layer": "primary",
        "transition_in": "cut",
        "transition_out": "cut",
        "reason": "hook_preroll_cold_open",
        "metadata": {
            "is_hook_preroll": True,
            "added_duration_seconds": round(added_duration, 3),
            "original_source_in": src_in,
            "original_source_out": src_out,
        },
    }

    # Insert pre-roll at index 0
    cuts = mutated.setdefault("cuts", [])
    cuts.insert(0, preroll_cut)

    # Shift body audio narration segments
    audio = mutated.setdefault("audio", {})
    narration = audio.setdefault("narration", {})
    if "segments" in narration and isinstance(narration["segments"], list):
        for seg in narration["segments"]:
            if isinstance(seg, dict):
                seg["start_seconds"] = round(float(seg.get("start_seconds", 0.0)) + added_duration, 3)
                if "end_seconds" in seg:
                    seg["end_seconds"] = round(float(seg["end_seconds"]) + added_duration, 3)

    # Shift body SFX
    if "sfx" in audio and isinstance(audio["sfx"], list):
        for s in audio["sfx"]:
            if isinstance(s, dict):
                s["start_seconds"] = round(float(s.get("start_seconds", 0.0)) + added_duration, 3)

    # Shift existing overlays
    overlays = mutated.setdefault("overlays", [])
    for ov in overlays:
        if isinstance(ov, dict):
            ov["start_seconds"] = round(float(ov.get("start_seconds", 0.0)) + added_duration, 3)
            ov["end_seconds"] = round(float(ov.get("end_seconds", 0.0)) + added_duration, 3)

    return mutated, added_duration
