"""Tests for HookGuard Phase 1: Schemas, canonical EDL fingerprints, and policy plumbing."""

from __future__ import annotations

import copy
import pytest
from pathlib import Path

from schemas.artifacts import load_schema, validate_artifact
from lib.checkpoint import CheckpointValidationError, validate_checkpoint, write_checkpoint
from lib.hook_guard.config import HookPolicy, load_hook_policy
from lib.hook_guard.canonical_edl import (
    canonicalize_body_edl,
    compute_body_edl_fingerprint,
    verify_body_edl_preservation,
)


def sample_valid_hook_plan(status="PASS", mode="auto", candidate_status="PASS"):
    return {
        "version": "1.0",
        "status": status,
        "project_id": "test-project",
        "policy": {
            "mode": mode,
            "preserve_body_edl": True,
            "allow_preroll": False,
            "max_added_duration_seconds": 0.0,
            "allow_generated_tts": False,
            "allow_claim_rewrite": False,
            "fail_behavior": "skip_hook",
        },
        "source": {
            "kind": "existing_video",
            "source_video_id": "main_video",
            "baseline_body_edl_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        },
        "candidates": [
            {
                "id": "cand-1",
                "intent": "problem_first",
                "mode": "overlay_text",
                "text": "The one mistake that ruins your video edit",
                "window": {"start_seconds": 0.0, "end_seconds": 2.5},
                "evidence": [
                    {
                        "kind": "transcript",
                        "source_id": "main_video",
                        "start_seconds": 5.0,
                        "end_seconds": 8.0,
                        "claim": "People make mistakes in pacing",
                    }
                ],
                "rank_features": {"relevance": 0.9, "coherence": 0.95},
                "score": 0.88,
                "proposed_runtime": "remotion",
            }
        ],
        "selected_candidate_id": "cand-1" if candidate_status == "PASS" else None,
        "guard_result": {
            "status": candidate_status,
            "rule_version": "hookguard-1",
            "reason_codes": ["PASS_CLEAN"] if candidate_status == "PASS" else ["SKIPPED_POLICY_OFF"],
        },
    }


def sample_baseline_edl():
    return {
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
        "cuts": [
            {
                "id": "cut-1",
                "source": "clip1.mp4",
                "in_seconds": 0.0,
                "out_seconds": 5.0,
                "speed": 1.0,
                "layer": "primary",
            },
            {
                "id": "cut-2",
                "source": "clip2.mp4",
                "in_seconds": 5.0,
                "out_seconds": 12.0,
                "speed": 1.0,
                "layer": "primary",
            },
        ],
        "audio": {
            "narration": {
                "segments": [
                    {"asset_id": "narr-1", "start_seconds": 0.0, "end_seconds": 4.8},
                    {"asset_id": "narr-2", "start_seconds": 5.2, "end_seconds": 11.5},
                ]
            },
            "music": {
                "asset_id": "bgm.mp3",
                "volume": 0.2,
                "fade_in_seconds": 1.0,
                "fade_out_seconds": 1.5,
            },
        },
        "overlays": [],
    }


# --- Schema Tests ---

def test_hook_plan_schema_valid():
    plan = sample_valid_hook_plan(status="PASS", candidate_status="PASS")
    validate_artifact("hook_plan", plan)


def test_hook_plan_schema_skipped_valid():
    plan = sample_valid_hook_plan(status="SKIPPED", candidate_status="SKIPPED")
    validate_artifact("hook_plan", plan)


def test_hook_plan_schema_invalid_missing_fields():
    plan = sample_valid_hook_plan()
    del plan["guard_result"]
    with pytest.raises(Exception):
        validate_artifact("hook_plan", plan)


def test_hook_plan_schema_invalid_intent():
    plan = sample_valid_hook_plan()
    plan["candidates"][0]["intent"] = "invalid_clickbait"
    with pytest.raises(Exception):
        validate_artifact("hook_plan", plan)


def test_hook_plan_schema_invalid_mode():
    plan = sample_valid_hook_plan()
    plan["candidates"][0]["mode"] = "unsupported_3d_vr"
    with pytest.raises(Exception):
        validate_artifact("hook_plan", plan)


# --- Canonical EDL Tests ---

def test_canonical_edl_determinism():
    edl1 = sample_baseline_edl()
    edl2 = copy.deepcopy(edl1)
    # Different key ordering
    edl2["cuts"] = [dict(reversed(list(c.items()))) for c in edl2["cuts"]]

    fp1 = compute_body_edl_fingerprint(edl1)
    fp2 = compute_body_edl_fingerprint(edl2)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_canonical_edl_preserves_overlay_injection():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    # Inject hook overlay
    mutated_edl = copy.deepcopy(edl)
    mutated_edl["overlays"].append({
        "asset_id": "hook_title_card",
        "start_seconds": 0.0,
        "end_seconds": 2.5,
        "position": {"x": 0.5, "y": 0.2, "width": 0.8, "height": 0.2},
    })

    ok, reason = verify_body_edl_preservation(baseline_fp, mutated_edl, mode="overlay")
    assert ok is True
    assert reason == ""


def test_canonical_edl_detects_body_cut_mutation():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    # Mutate a body cut
    mutated_edl = copy.deepcopy(edl)
    mutated_edl["cuts"][0]["out_seconds"] = 4.5  # shortened cut!

    ok, reason = verify_body_edl_preservation(baseline_fp, mutated_edl, mode="overlay")
    assert ok is False
    assert "mismatch" in reason


def test_canonical_edl_detects_audio_schedule_mutation():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    # Mutate narration timing
    mutated_edl = copy.deepcopy(edl)
    mutated_edl["audio"]["narration"]["segments"][0]["start_seconds"] = 0.5

    ok, reason = verify_body_edl_preservation(baseline_fp, mutated_edl, mode="overlay")
    assert ok is False
    assert "mismatch" in reason


def test_canonical_edl_preroll_normalization():
    edl = sample_baseline_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    preroll_duration = 3.0
    mutated_edl = copy.deepcopy(edl)
    # Add tagged preroll cut at index 0
    preroll_cut = {
        "id": "hook_preroll_cut",
        "source": "clip1.mp4",
        "in_seconds": 10.0,
        "out_seconds": 13.0,
        "speed": 1.0,
        "layer": "primary",
        "metadata": {"is_hook_preroll": True},
    }
    mutated_edl["cuts"].insert(0, preroll_cut)

    # Shift body narration by preroll_duration
    for seg in mutated_edl["audio"]["narration"]["segments"]:
        seg["start_seconds"] += preroll_duration
        if "end_seconds" in seg:
            seg["end_seconds"] += preroll_duration

    ok, reason = verify_body_edl_preservation(
        baseline_fp,
        mutated_edl,
        mode="extractive_preroll",
        preroll_duration=preroll_duration,
    )
    assert ok is True
    assert reason == ""


# --- Policy and Checkpoint Tests ---

def test_policy_loading_defaults(tmp_path):
    empty_cfg = tmp_path / "empty.yaml"
    empty_cfg.write_text("hooks: {}\n")
    policy = load_hook_policy(config_path=empty_cfg)
    assert policy.enabled is False
    assert policy.mode == "off"
    assert policy.is_active() is False


def test_policy_loading_active_from_profiles():
    policy = load_hook_policy()
    assert policy.enabled is True
    assert policy.mode == "auto"
    assert policy.is_active() is True


def test_policy_loading_env_overrides(monkeypatch):
    monkeypatch.setenv("HOOKGUARD_ENABLED", "1")
    monkeypatch.setenv("HOOKGUARD_MODE", "required")
    monkeypatch.setenv("HOOKGUARD_ALLOW_PREROLL", "1")

    policy = load_hook_policy()
    assert policy.enabled is True
    assert policy.mode == "required"
    assert policy.allow_preroll is True
    assert policy.is_active() is True


def test_checkpoint_passes_when_off(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOKGUARD_ENABLED", "0")
    monkeypatch.setenv("HOOKGUARD_MODE", "off")

    ckpt = {
        "version": "1.0",
        "project_id": "test-p",
        "pipeline_type": "framework-smoke",
        "stage": "research",
        "status": "completed",
        "timestamp": "2026-10-18T00:00:00Z",
        "artifacts": {
            "research_brief": {
                "version": "1.0",
                "topic": "Test",
                "research_date": "2026-10-18",
                "landscape": {
                    "existing_content": [
                        {"title": "E1", "source": "yt", "angle": "a1", "what_it_covers": "c1"},
                        {"title": "E2", "source": "yt", "angle": "a2", "what_it_covers": "c2"},
                        {"title": "E3", "source": "yt", "angle": "a3", "what_it_covers": "c3"},
                    ],
                    "saturated_angles": ["sat1"],
                    "underserved_gaps": ["gap1"],
                },
                "data_points": [
                    {"claim": "Claim 1", "source_url": "https://example.com/1", "credibility": "primary_source"},
                    {"claim": "Claim 2", "source_url": "https://example.com/2", "credibility": "primary_source"},
                    {"claim": "Claim 3", "source_url": "https://example.com/3", "credibility": "primary_source"},
                ],
                "audience_insights": {
                    "common_questions": ["Q1", "Q2", "Q3"],
                    "misconceptions": [{"myth": "M1", "reality": "R1"}],
                    "knowledge_level": "Beginner",
                },
                "angles_discovered": [
                    {"name": "A1", "hook": "H1", "type": "evergreen", "why_now": "Now", "grounded_in": ["claim1"]},
                    {"name": "A2", "hook": "H2", "type": "contrarian", "why_now": "Now", "grounded_in": ["claim2"]},
                    {"name": "A3", "hook": "H3", "type": "trending", "why_now": "Now", "grounded_in": ["claim3"]},
                ],
                "sources": [
                    {"url": "https://example.com/1", "title": "S1", "used_for": "data"},
                    {"url": "https://example.com/2", "title": "S2", "used_for": "data"},
                    {"url": "https://example.com/3", "title": "S3", "used_for": "data"},
                    {"url": "https://example.com/4", "title": "S4", "used_for": "data"},
                    {"url": "https://example.com/5", "title": "S5", "used_for": "data"},
                ],
            }
        },
    }
    # No error raised without hook_plan
    validate_checkpoint(ckpt)


def test_checkpoint_rejects_rejected_hook_plan(monkeypatch):
    monkeypatch.setenv("HOOKGUARD_ENABLED", "1")
    monkeypatch.setenv("HOOKGUARD_MODE", "auto")

    bad_plan = sample_valid_hook_plan(status="REJECTED", candidate_status="REJECTED")
    bad_plan["guard_result"]["status"] = "REJECTED"
    bad_plan["guard_result"]["reason_codes"] = ["REJECTED_BODY_EDL_MUTATED"]

    ckpt = {
        "version": "1.0",
        "project_id": "test-p",
        "pipeline_type": "clip-factory",
        "stage": "edit",
        "status": "completed",
        "timestamp": "2026-10-18T00:00:00Z",
        "artifacts": {
            "edit_decisions": sample_baseline_edl(),
            "hook_plan": bad_plan,
        },
    }

    with pytest.raises(CheckpointValidationError) as exc:
        validate_checkpoint(ckpt)
    assert "REJECTED hook_plan" in str(exc.value)


def test_checkpoint_enforces_hook_required_mode(monkeypatch):
    monkeypatch.setenv("HOOKGUARD_ENABLED", "1")
    monkeypatch.setenv("HOOKGUARD_MODE", "required")

    # Missing hook_plan in required mode must fail
    ckpt_missing = {
        "version": "1.0",
        "project_id": "test-p",
        "pipeline_type": "clip-factory",
        "stage": "edit",
        "status": "completed",
        "timestamp": "2026-10-18T00:00:00Z",
        "artifacts": {
            "edit_decisions": sample_baseline_edl(),
        },
    }
    with pytest.raises(CheckpointValidationError) as exc:
        validate_checkpoint(ckpt_missing)
    assert "HookGuard mode is 'required' but 'hook_plan' artifact is missing" in str(exc.value)

    # Valid PASS hook_plan in required mode must succeed
    valid_plan = sample_valid_hook_plan(status="PASS", candidate_status="PASS")
    ckpt_pass = {
        "version": "1.0",
        "project_id": "test-p",
        "pipeline_type": "clip-factory",
        "stage": "edit",
        "status": "completed",
        "timestamp": "2026-10-18T00:00:00Z",
        "artifacts": {
            "edit_decisions": sample_baseline_edl(),
            "hook_plan": valid_plan,
        },
    }
    validate_checkpoint(ckpt_pass)
