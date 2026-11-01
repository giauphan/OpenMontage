"""Voice timing alignment service for progressive SVG diagram flow.

Synchronizes diagram steps and connecting arrows to spoken voice narration,
using ASR word timestamps when available, or proportional sentence-level timing.

Target module size: < 350 lines.
Clean Architecture layer: Domain / Application Service.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def compute_step_timings_for_beat(
    narration: str,
    duration: float,
    num_steps: int = 4,
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    beat_start_s: float = 0.0,
    min_step_gap: float = 1.2,
) -> List[float]:
    """Compute relative start timestamps (in seconds from beat start) for each step.

    Parameters:
        narration: Narration text for the beat.
        duration: Total duration of the beat in seconds.
        num_steps: Number of progressive blocks to reveal.
        word_timestamps: Optional word-level timestamp entries [{"word": str, "start": float, "end": float}].
        beat_start_s: Absolute start time of the beat within the whole video.
        min_step_gap: Minimum gap between successive step reveals.

    Returns:
        A list of `num_steps` floats representing relative seconds from beat start.
    """
    if num_steps <= 1:
        return [0.2]

    duration = max(2.0, float(duration))

    # Path 1: Align via word timestamps if available
    if word_timestamps and len(word_timestamps) > 0:
        timings = _align_via_word_timestamps(
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
            duration=duration,
            num_steps=num_steps,
        )
        if timings and len(timings) == num_steps:
            return timings

    # Path 2: Align via sentence structure / word count
    return _align_via_sentence_proportions(
        narration=narration,
        duration=duration,
        num_steps=num_steps,
        min_step_gap=min_step_gap,
    )


def _align_via_word_timestamps(
    word_timestamps: List[Dict[str, Any]],
    beat_start_s: float,
    duration: float,
    num_steps: int,
) -> Optional[List[float]]:
    """Extract step timings from word timestamps bounded within [beat_start_s, beat_start_s + duration]."""
    beat_end_s = beat_start_s + duration
    # Filter words belonging to this beat window
    words_in_beat = [
        w for w in word_timestamps
        if isinstance(w, dict) and "start" in w and (beat_start_s - 0.5) <= float(w["start"]) <= (beat_end_s + 0.5)
    ]

    if len(words_in_beat) < num_steps:
        return None

    # Sort by start time
    words_in_beat.sort(key=lambda w: float(w["start"]))

    # Divide words into num_steps roughly equal buckets to find natural phrase starts
    total_w = len(words_in_beat)
    step_indices = [int(round(i * (total_w / num_steps))) for i in range(num_steps)]

    timings: List[float] = []
    prev_t = 0.1

    for i, idx in enumerate(step_indices):
        w_entry = words_in_beat[min(idx, total_w - 1)]
        raw_start = float(w_entry["start"]) - beat_start_s
        # Bound within beat duration
        rel_t = max(0.2, min(duration - 0.4, raw_start))
        # Ensure monotonic increase
        if rel_t <= prev_t:
            rel_t = prev_t + 0.8
        rel_t = min(rel_t, duration - (num_steps - i) * 0.4)
        timings.append(round(rel_t, 2))
        prev_t = rel_t

    return timings


def _align_via_sentence_proportions(
    narration: str,
    duration: float,
    num_steps: int,
    min_step_gap: float = 1.2,
) -> List[float]:
    """Compute step timings by proportional sentence or clause length."""
    # Split narration by sentence or major clause boundaries (. , ; :)
    clean_text = narration.strip()
    sentences = [s.strip() for s in re.split(r'[.!?]+|\b(?:and then|however|because|then|where)\b', clean_text) if s.strip()]

    # If we have multiple sentences matching or close to step count
    if len(sentences) >= num_steps:
        sentence_lengths = [max(1, len(s.split())) for s in sentences[:num_steps]]
        total_words = sum(sentence_lengths)
        timings = [0.2]
        accum_words = sentence_lengths[0]
        # Allocate between 0.2s and duration - 0.6s
        usable_dur = max(1.0, duration - 1.0)
        for i in range(1, num_steps):
            frac = accum_words / total_words
            t = 0.2 + (frac * usable_dur)
            timings.append(round(max(timings[-1] + min_step_gap, min(duration - 0.4, t)), 2))
            accum_words += sentence_lengths[i]
        return timings

    # Default uniform / progression curve
    # Step 1 starts at 0.2s
    # Remaining steps span across the beat duration with comfortable breathing room
    timings = [0.2]
    usable_span = max(1.0, duration - 1.2)
    step_interval = usable_span / (num_steps - 1)

    for i in range(1, num_steps):
        t = round(0.2 + i * step_interval, 2)
        # Guarantee minimum step gap
        t = max(timings[-1] + min_step_gap, min(duration - 0.4, t))
        timings.append(t)

    return timings


def generate_progressive_svg_style(
    step_timings: List[float],
    arrow_lead_time: float = 0.35,
) -> str:
    """Generate CSS keyframe animation rules embedded inside SVG for voice-timed display."""
    lines: List[str] = [
        "  <style>",
        "    @keyframes flowStepAppear {",
        "      0% { opacity: 0; transform: translateY(22px) scale(0.96); }",
        "      75% { transform: translateY(-2px) scale(1.01); }",
        "      100% { opacity: 1; transform: translateY(0) scale(1); }",
        "    }",
        "    @keyframes flowArrowDraw {",
        "      0% { opacity: 0; transform: scaleY(0.4); }",
        "      100% { opacity: 1; transform: scaleY(1); }",
        "    }",
        "    @keyframes drawArrowPath {",
        "      0% { stroke-dashoffset: 120; opacity: 0; }",
        "      20% { opacity: 1; }",
        "      100% { stroke-dashoffset: 0; opacity: 1; }",
        "    }",
        "    @keyframes popPolygon {",
        "      0% { transform: scale(0); opacity: 0; }",
        "      100% { transform: scale(1); opacity: 1; }",
        "    }",
        "    @keyframes ctaPulse {",
        "      0%, 100% { filter: drop-shadow(0 0 10px rgba(56, 189, 248, 0.35)); }",
        "      50% { filter: drop-shadow(0 0 24px rgba(56, 189, 248, 0.75)); }",
        "    }",
        "    .flow-step {",
        "      opacity: 0;",
        "      animation: flowStepAppear 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;",
        "      transform-origin: center center;",
        "      filter: drop-shadow(0 4px 16px rgba(0, 0, 0, 0.45));",
        "    }",
        "    .flow-arrow {",
        "      opacity: 0;",
        "      animation: flowArrowDraw 0.35s ease-out forwards;",
        "      transform-origin: top center;",
        "    }",
        "    .flow-arrow path, .flow-arrow line {",
        "      stroke-dasharray: 120;",
        "      stroke-dashoffset: 120;",
        "      animation: drawArrowPath 0.4s ease-out forwards;",
        "    }",
        "    .flow-arrow polygon {",
        "      transform-origin: center center;",
        "      animation: popPolygon 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;",
        "    }",
        "    .flow-header {",
        "      animation-delay: 0.1s;",
        "    }",
        "    #flow-cta-banner {",
        "      animation: flowStepAppear 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards, ctaPulse 3.5s ease-in-out infinite;",
        "    }",
    ]

    for idx, t in enumerate(step_timings, start=1):
        step_id = f"flow-step-{idx}"
        lines.append(f"    #{step_id} {{ animation-delay: {t:.2f}s; }}")

        if idx > 1:
            arrow_id = f"flow-arrow-{idx-1}"
            arrow_t = max(0.1, t - arrow_lead_time)
            lines.append(f"    #{arrow_id} {{ animation-delay: {arrow_t:.2f}s; }}")
            lines.append(f"    #{arrow_id} path {{ animation-delay: {arrow_t:.2f}s; }}")
            lines.append(f"    #{arrow_id} polygon {{ animation-delay: {arrow_t + 0.15:.2f}s; }}")

    if step_timings:
        lines.append(f"    #flow-cta-banner {{ animation-delay: {step_timings[-1]:.2f}s; }}")

    lines.append("  </style>")
    return "\n".join(lines)
