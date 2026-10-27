"""Normalization and conversion layer for visual plan formats into TimedVisualBeat entities.

Converts either:
1. Daily News visual plan format (schemas/news/news_visual_plan.schema.json)
2. Fixed Niche storyboard plan format (lib/fixed_niche/storyboard.py)
into canonical TimedVisualBeat domain entities, validating time and hold bounds.

Target module size: < 450 lines.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from lib.visual_style.spec import TimedVisualBeat

logger = logging.getLogger(__name__)

MIN_TOTAL_DURATION = 65.0
MAX_TOTAL_DURATION = 75.0
MAX_BEAT_HOLD_SECONDS = 12.0
MIN_BEAT_HOLD_SECONDS = 0.5
MIN_BEATS_COUNT = 6


class PlanNormalizationError(ValueError):
    """Raised when a visual plan violates timing, contiguity, or contract bounds."""
    pass


def normalize_beats(
    raw_beats: List[Dict[str, Any]],
    target_duration: Optional[float] = None,
    enforce_strict_bounds: bool = True,
) -> List[TimedVisualBeat]:
    """Normalize a list of beat dictionaries from either format into TimedVisualBeat.

    Validates:
    - start_seconds and end_seconds are contiguous
    - each beat hold is 0 < hold <= 12.0s
    - total duration is within [65.0, 75.0]
    """
    if not raw_beats:
        raise PlanNormalizationError("Cannot normalize empty beats list")

    normalized: List[TimedVisualBeat] = []
    prev_end = 0.0

    for idx, raw in enumerate(raw_beats):
        if not isinstance(raw, dict):
            raise PlanNormalizationError(f"Beat at index {idx} is not a dictionary: {raw!r}")

        beat_id = str(raw.get("id") or raw.get("beat_id") or f"B{idx+1:02d}")
        section_id = str(raw.get("script_section_id") or raw.get("section_id") or f"S{idx+1:02d}")

        start_val = raw.get("start_seconds") if raw.get("start_seconds") is not None else raw.get("start_s")
        end_val = raw.get("end_seconds") if raw.get("end_seconds") is not None else raw.get("end_s")

        if start_val is None or end_val is None:
            raise PlanNormalizationError(f"Beat {beat_id} missing start/end seconds")

        start_s = round(float(start_val), 4)
        end_s = round(float(end_val), 4)

        # Check contiguity
        if abs(start_s - prev_end) > 0.05:
            if enforce_strict_bounds:
                raise PlanNormalizationError(
                    f"Beat {beat_id} start_seconds ({start_s}) does not match previous end ({prev_end})"
                )
            else:
                start_s = prev_end

        hold = round(end_s - start_s, 4)
        if hold <= 0:
            raise PlanNormalizationError(f"Beat {beat_id} has invalid non-positive hold ({hold}s)")

        if enforce_strict_bounds and hold > MAX_BEAT_HOLD_SECONDS + 0.001:
            raise PlanNormalizationError(
                f"Beat {beat_id} hold ({hold}s) exceeds maximum allowed hold of {MAX_BEAT_HOLD_SECONDS}s"
            )

        claim_ids = [str(c) for c in raw.get("claim_ids", []) if c]
        if not claim_ids and raw.get("claim_id"):
            claim_ids = [str(raw["claim_id"])]

        visual_intent = str(
            raw.get("visual_intent")
            or raw.get("expected_screen_state")
            or raw.get("story_function")
            or f"Beat {idx+1}"
        )

        asset_ids_raw = raw.get("asset_ids") or ([raw["asset_id"]] if raw.get("asset_id") else [])
        asset_ids = [str(a) for a in asset_ids_raw if a]

        beat = TimedVisualBeat(
            id=beat_id,
            section_id=section_id,
            start_seconds=start_s,
            end_seconds=end_s,
            claim_ids=claim_ids,
            visual_intent=visual_intent,
            asset_ids=asset_ids,
            story_function=str(raw.get("story_function", "scene")),
            visual_kind=str(raw.get("visual_kind", "svg_diagram")),
            evidence_class=str(raw.get("evidence_class", "conceptual_diagram")),
        )
        normalized.append(beat)
        prev_end = end_s

    total_duration = prev_end
    if target_duration is not None and abs(total_duration - target_duration) > 0.5:
        if enforce_strict_bounds:
            raise PlanNormalizationError(
                f"Normalized total duration ({total_duration}s) does not match target ({target_duration}s)"
            )

    if enforce_strict_bounds:
        if total_duration < MIN_TOTAL_DURATION - 0.05 or total_duration > MAX_TOTAL_DURATION + 0.05:
            raise PlanNormalizationError(
                f"Total duration ({total_duration}s) outside allowed [{MIN_TOTAL_DURATION}, {MAX_TOTAL_DURATION}]s range"
            )
        if len(normalized) < MIN_BEATS_COUNT:
            raise PlanNormalizationError(
                f"Beats count ({len(normalized)}) is below minimum requirement of {MIN_BEATS_COUNT}"
            )

    return normalized


def split_long_beats_to_fit_ceiling(
    beats: List[TimedVisualBeat],
    max_hold: float = MAX_BEAT_HOLD_SECONDS,
) -> List[TimedVisualBeat]:
    """Helper to partition any beats exceeding max_hold into contiguous sub-beats."""
    result: List[TimedVisualBeat] = []
    for beat in beats:
        hold = beat.end_seconds - beat.start_seconds
        if hold <= max_hold:
            result.append(beat)
            continue

        # Split into ceil(hold / max_hold) sub-beats
        num_splits = int(hold // max_hold) + (1 if hold % max_hold > 0 else 0)
        split_dur = round(hold / num_splits, 4)
        current_start = beat.start_seconds

        for s_idx in range(num_splits):
            current_end = (
                beat.end_seconds if s_idx == num_splits - 1 else round(current_start + split_dur, 4)
            )
            sub_beat = TimedVisualBeat(
                id=f"{beat.id}_{s_idx+1}",
                section_id=beat.section_id,
                start_seconds=current_start,
                end_seconds=current_end,
                claim_ids=beat.claim_ids,
                visual_intent=f"{beat.visual_intent} (part {s_idx+1})",
                asset_ids=beat.asset_ids,
                story_function=beat.story_function,
                visual_kind=beat.visual_kind,
                evidence_class=beat.evidence_class,
            )
            result.append(sub_beat)
            current_start = current_end

    return result
