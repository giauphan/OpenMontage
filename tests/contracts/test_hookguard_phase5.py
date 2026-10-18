"""Tests for HookGuard Phase 5: Extractive Pre-Roll."""

from __future__ import annotations

import copy
import pytest

from lib.hook_guard.canonical_edl import compute_body_edl_fingerprint, verify_body_edl_preservation
from lib.hook_guard.config import HookPolicy
from lib.hook_guard.guard import evaluate_hook_guard
from lib.hook_guard.preroll import apply_extractive_preroll, verify_preroll_boundaries


def sample_baseline_edl():
    return {
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
        "cuts": [
            {
                "id": "cut-1",
                "source": "interview.mp4",
                "in_seconds": 0.0,
                "out_seconds": 15.0,
                "speed": 1.0,
                "layer": "primary",
            },
            {
                "id": "cut-2",
                "source": "interview.mp4",
                "in_seconds": 15.0,
                "out_seconds": 45.0,
                "speed": 1.0,
                "layer": "primary",
            },
        ],
        "audio": {
            "narration": {
                "segments": [
                    {"asset_id": "narr-1", "start_seconds": 0.0, "end_seconds": 14.5},
                    {"asset_id": "narr-2", "start_seconds": 15.0, "end_seconds": 44.0},
                ]
            }
        },
        "overlays": [],
    }


def sample_transcript_words():
    return [
        {"word": "Welcome", "start": 0.0, "end": 0.5},
        {"word": "to", "start": 0.5, "end": 0.7},
        {"word": "this", "start": 0.7, "end": 1.0},
        {"word": "special", "start": 1.0, "end": 1.5},
        {"word": "episode.", "start": 1.5, "end": 2.2},
        # Climax moment from 30.0s to 33.0s
        {"word": "The", "start": 30.0, "end": 30.2},
        {"word": "system", "start": 30.2, "end": 30.8},
        {"word": "completely", "start": 30.8, "end": 31.5},
        {"word": "crashed.", "start": 31.5, "end": 32.5},
    ]


# --- Boundary Tests ---

def test_preroll_detects_mid_word_cut():
    words = sample_transcript_words()
    # 31.0 is right in the middle of "completely" (30.8 to 31.5)
    is_valid, flags = verify_preroll_boundaries(source_in=31.0, source_out=33.0, transcript_words=words)
    assert is_valid is False
    assert flags["mid_word_cut"] is True


def test_preroll_accepts_clean_word_and_sentence_boundaries():
    words = sample_transcript_words()
    # 30.0 to 32.6 is clean start of "The" and ends after "crashed."
    is_valid, flags = verify_preroll_boundaries(source_in=30.0, source_out=32.6, transcript_words=words)
    assert is_valid is True
    assert flags["mid_word_cut"] is False
    assert flags["mid_sentence_cut"] is False


# --- EDL Preservation Tests ---

def test_preroll_application_preserves_body_edl():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    preroll_span = {
        "source_in_seconds": 30.0,
        "source_out_seconds": 33.0,
    }
    mutated_edl, added_dur = apply_extractive_preroll(
        edl,
        preroll_span,
        source_id="interview.mp4",
    )

    assert added_dur == 3.0
    assert len(mutated_edl["cuts"]) == 3
    assert mutated_edl["cuts"][0]["metadata"]["is_hook_preroll"] is True
    # Original cuts are still present
    assert mutated_edl["cuts"][1]["id"] == "cut-1"
    assert mutated_edl["cuts"][2]["id"] == "cut-2"

    # Narration should be shifted by added_dur
    assert mutated_edl["audio"]["narration"]["segments"][0]["start_seconds"] == 3.0
    assert mutated_edl["audio"]["narration"]["segments"][1]["start_seconds"] == 18.0

    # Verification must pass with time_offset=added_dur
    ok, err = verify_body_edl_preservation(
        baseline_fp,
        mutated_edl,
        mode="extractive_preroll",
        preroll_duration=added_dur,
    )
    assert ok is True
    assert err == ""


# --- Guard Tests ---

def test_guard_rejects_preroll_when_disallowed():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    cand = {
        "id": "cand-preroll",
        "intent": "visual_payoff",
        "mode": "extractive_preroll",
        "text": "The moment the system crashed",
        "window": {"start_seconds": 0.0, "end_seconds": 3.0},
        "preroll_span": {
            "source_in_seconds": 30.0,
            "source_out_seconds": 33.0,
            "added_duration_seconds": 3.0,
        },
        "evidence": [
            {
                "kind": "transcript",
                "source_id": "interview.mp4",
                "start_seconds": 30.0,
                "end_seconds": 33.0,
                "claim": "The system completely crashed",
            }
        ],
    }

    # Policy disallows preroll
    policy = HookPolicy(enabled=True, mode="auto", allow_preroll=False)
    res = evaluate_hook_guard(
        candidate=cand,
        policy=policy,
        baseline_body_edl_sha256=baseline_fp,
        mutated_edl=edl,
    )
    assert res["status"] == "REJECTED"
    assert "REJECTED_PREROLL_DISALLOWED" in res["reason_codes"]


def test_guard_accepts_valid_preroll():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    cand = {
        "id": "cand-preroll",
        "intent": "visual_payoff",
        "mode": "extractive_preroll",
        "text": "The system completely crashed",
        "window": {"start_seconds": 0.0, "end_seconds": 3.0},
        "preroll_span": {
            "source_in_seconds": 30.0,
            "source_out_seconds": 33.0,
            "added_duration_seconds": 3.0,
        },
        "evidence": [
            {
                "kind": "transcript",
                "source_id": "interview.mp4",
                "start_seconds": 30.0,
                "end_seconds": 33.0,
                "claim": "The system completely crashed",
            }
        ],
    }

    mutated_edl, added_dur = apply_extractive_preroll(
        edl,
        cand["preroll_span"],
        source_id="interview.mp4",
    )

    policy = HookPolicy(
        enabled=True,
        mode="auto",
        allow_preroll=True,
        max_added_duration_seconds=5.0,
    )
    res = evaluate_hook_guard(
        candidate=cand,
        policy=policy,
        baseline_body_edl_sha256=baseline_fp,
        mutated_edl=mutated_edl,
    )
    assert res["status"] == "PASS"
    assert "PASS_CLEAN" in res["reason_codes"]
