"""Tests for lib.visual_style.normalization.

Covers AC-007, AC-008.
"""
from __future__ import annotations

import pytest
from lib.visual_style.normalization import (
    MAX_BEAT_HOLD_SECONDS,
    MIN_TOTAL_DURATION,
    MAX_TOTAL_DURATION,
    PlanNormalizationError,
    normalize_beats,
    split_long_beats_to_fit_ceiling,
)
from lib.visual_style.spec import TimedVisualBeat


def test_normalize_daily_news_format():
    """Daily News format (id, start_seconds, end_seconds, asset_ids) normalizes cleanly."""
    raw_beats = [
        {
            "id": f"vb-{i+1:02d}",
            "script_section_id": f"scene-{i+1}",
            "start_seconds": i * 9.0,
            "end_seconds": (i + 1) * 9.0,
            "claim_ids": [f"C{i+1}"],
            "asset_ids": [f"asset_{i+1}"],
            "story_function": "stage",
            "visual_kind": "svg_diagram",
            "evidence_class": "conceptual_diagram",
            "visual_intent": f"Beat {i+1} intent",
        }
        for i in range(8)
    ]
    # Total duration is 8 * 9.0 = 72.0s
    normalized = normalize_beats(raw_beats)
    assert len(normalized) == 8
    assert normalized[0].id == "vb-01"
    assert normalized[0].start_seconds == 0.0
    assert normalized[0].end_seconds == 9.0
    assert normalized[-1].end_seconds == 72.0
    for b in normalized:
        assert 0 < b.duration_seconds <= MAX_BEAT_HOLD_SECONDS


def test_normalize_fixed_niche_format():
    """Fixed Niche format (beat_id, start_s, end_s, asset_id) normalizes cleanly."""
    raw_beats = [
        {
            "beat_id": f"B{i+1:02d}",
            "script_section_id": f"S{i+1:02d}",
            "start_s": i * 10.0,
            "end_s": (i + 1) * 10.0,
            "claim_ids": [f"C{i+1}"],
            "asset_id": f"beat_{i+1}",
            "story_function": "explainer",
            "visual_kind": "svg_diagram",
            "expected_screen_state": f"State {i+1}",
        }
        for i in range(7)
    ]
    # Total duration is 70.0s
    normalized = normalize_beats(raw_beats)
    assert len(normalized) == 7
    assert normalized[0].id == "B01"
    assert normalized[0].start_seconds == 0.0
    assert normalized[-1].end_seconds == 70.0


def test_reject_beat_hold_exceeding_12s():
    """Beat with duration > 12.0s must raise PlanNormalizationError."""
    raw_beats = [
        {"id": "B01", "start_seconds": 0.0, "end_seconds": 10.0, "claim_ids": ["C1"]},
        {"id": "B02", "start_seconds": 10.0, "end_seconds": 25.0, "claim_ids": ["C2"]},  # 15s!
        {"id": "B03", "start_seconds": 25.0, "end_seconds": 70.0, "claim_ids": ["C3"]},
    ]
    with pytest.raises(PlanNormalizationError, match="exceeds maximum allowed hold"):
        normalize_beats(raw_beats)


def test_reject_non_contiguous_beats():
    """Gap or overlap between beats must raise PlanNormalizationError."""
    raw_beats = [
        {"id": "B01", "start_seconds": 0.0, "end_seconds": 10.0, "claim_ids": ["C1"]},
        {"id": "B02", "start_seconds": 12.0, "end_seconds": 22.0, "claim_ids": ["C2"]},  # gap of 2s!
    ]
    with pytest.raises(PlanNormalizationError, match="does not match previous end"):
        normalize_beats(raw_beats)


def test_reject_duration_outside_65_to_75s():
    """Total duration < 65s or > 75s must raise PlanNormalizationError."""
    # Under 65s
    short_beats = [
        {"id": f"B{i+1}", "start_seconds": i * 8.0, "end_seconds": (i + 1) * 8.0, "claim_ids": ["C1"]}
        for i in range(6)
    ]  # 48s total
    with pytest.raises(PlanNormalizationError, match="outside allowed"):
        normalize_beats(short_beats)


def test_split_long_beats_to_fit_ceiling():
    """split_long_beats_to_fit_ceiling correctly partitions long holds into <=12s chunks."""
    long_beat = TimedVisualBeat(
        id="B01",
        section_id="S01",
        start_seconds=0.0,
        end_seconds=20.0,  # 20s hold!
        claim_ids=["C1"],
        visual_intent="Long explanation",
    )
    splits = split_long_beats_to_fit_ceiling([long_beat], max_hold=12.0)
    assert len(splits) == 2
    assert splits[0].start_seconds == 0.0
    assert splits[0].end_seconds == 10.0
    assert splits[1].start_seconds == 10.0
    assert splits[1].end_seconds == 20.0
    for s in splits:
        assert s.duration_seconds <= 12.0
