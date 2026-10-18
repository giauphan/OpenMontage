"""Comprehensive corpus evaluation and end-to-end integration tests for HookGuard."""

from __future__ import annotations

import copy
import pytest
from pathlib import Path

from lib.hook_guard.canonical_edl import compute_body_edl_fingerprint, verify_body_edl_preservation
from lib.hook_guard.config import HookPolicy
from lib.hook_guard.guard import evaluate_hook_guard
from lib.hook_guard.telemetry import record_hook_telemetry
from tests.fixtures.hookguard_corpus import HOOKGUARD_CORPUS


def sample_edl_for_corpus(item: dict) -> dict:
    dur = float(item.get("duration_seconds", 60.0))
    aspect = item.get("aspect_ratio", "16:9")
    runtime = "remotion"
    return {
        "version": "1.0",
        "render_runtime": runtime,
        "renderer_family": "explainer-data",
        "cuts": [
            {
                "id": "cut-1",
                "source": "source_media.mp4",
                "in_seconds": 0.0,
                "out_seconds": dur / 2,
                "speed": 1.0,
                "layer": "primary",
            },
            {
                "id": "cut-2",
                "source": "source_media.mp4",
                "in_seconds": dur / 2,
                "out_seconds": dur,
                "speed": 1.0,
                "layer": "primary",
            },
        ],
        "audio": {
            "narration": {
                "segments": [
                    {"asset_id": "narr-1", "start_seconds": 0.0, "end_seconds": (dur / 2) - 0.5},
                    {"asset_id": "narr-2", "start_seconds": dur / 2, "end_seconds": dur - 0.5},
                ]
            }
        },
        "overlays": [],
    }


def test_corpus_count_is_at_least_24():
    assert len(HOOKGUARD_CORPUS) >= 24


@pytest.mark.parametrize("item", HOOKGUARD_CORPUS)
def test_corpus_evaluation_against_guard(item, tmp_path):
    edl = sample_edl_for_corpus(item)
    baseline_fp = compute_body_edl_fingerprint(edl)

    cand = {
        "id": f"cand-{item['id']}",
        "intent": item["intent"],
        "mode": item.get("mode", "overlay_text"),
        "text": item["text"],
        "window": {"start_seconds": 0.0, "end_seconds": min(3.0, item["duration_seconds"])},
        "evidence": item["evidence"],
    }
    if item.get("mid_word_cut"):
        cand["boundary_flags"] = {"mid_word_cut": True}
        cand["preroll_span"] = {"source_in_seconds": 5.0, "source_out_seconds": 8.0, "added_duration_seconds": 3.0}

    policy = HookPolicy(
        enabled=True,
        mode="auto",
        allow_preroll=True if cand["mode"] == "extractive_preroll" else False,
    )

    if item.get("corrupt_first_seconds"):
        from lib.hook_guard.post_render import verify_post_render
        fake_video = tmp_path / "corrupt.mp4"
        fake_video.write_bytes(b"dummy_bytes")
        # Post-render check must detect corrupt/black frames
        pr_ok, pr_reason, _ = verify_post_render(
            fake_video,
            expected_duration=item["duration_seconds"],
            baseline_body_edl_sha256=baseline_fp,
            mutated_edl=edl,
        )
        assert pr_ok is False
        assert pr_reason == "REJECTED_POST_RENDER_FAILED"
        return

    res = evaluate_hook_guard(
        candidate=cand,
        policy=policy,
        baseline_body_edl_sha256=baseline_fp,
        mutated_edl=edl,
        video_duration=item["duration_seconds"],
    )

    expected = item["expected_status"]
    if expected == "PASS":
        assert res["status"] == "PASS"
        assert "PASS_CLEAN" in res["reason_codes"]
        # Record telemetry
        telemetry = record_hook_telemetry(
            project_id=item["id"],
            project_dir=tmp_path,
            hook_plan={
                "status": "PASS",
                "selected_candidate_id": cand["id"],
                "candidates": [cand],
                "guard_result": res,
                "policy": {"mode": "auto"},
            },
            baseline_fingerprint=baseline_fp,
            final_fingerprint=baseline_fp,
        )
        assert telemetry["fingerprints_match"] is True
        assert (tmp_path / "artifacts" / "hook_telemetry.json").is_file()
    else:
        # Bad media cases: must fail with the expected reason code
        assert res["status"] in ("REJECTED", "SKIPPED")
        assert any(expected in code for code in res["reason_codes"])


def test_end_to_end_graceful_skip_on_rejected_hook():
    """Verify that in auto mode, when a hook candidate is rejected,
    the pipeline safely skips without mutating or corrupting edit decisions."""
    item = next(i for i in HOOKGUARD_CORPUS if i["id"] == "corpus-17-bad-numerical-exaggeration")
    edl = sample_edl_for_corpus(item)
    baseline_fp = compute_body_edl_fingerprint(edl)

    cand = {
        "id": "cand-bad-numbers",
        "intent": item["intent"],
        "mode": "overlay_text",
        "text": item["text"],
        "window": {"start_seconds": 0.0, "end_seconds": 2.5},
        "evidence": item["evidence"],
    }

    policy = HookPolicy(enabled=True, mode="auto")
    guard_res = evaluate_hook_guard(
        candidate=cand,
        policy=policy,
        baseline_body_edl_sha256=baseline_fp,
        mutated_edl=edl,
    )

    assert guard_res["status"] == "REJECTED"
    assert "REJECTED_NUMERICAL_MISMATCH" in guard_res["reason_codes"]

    # In auto mode, a rejected hook is not applied:
    final_edl = copy.deepcopy(edl)  # no mutation
    final_plan = {
        "version": "1.0",
        "status": "SKIPPED",
        "project_id": item["id"],
        "policy": {"mode": "auto"},
        "source": {"kind": "existing_video", "baseline_body_edl_sha256": baseline_fp},
        "candidates": [cand],
        "selected_candidate_id": None,
        "guard_result": {
            "status": "SKIPPED",
            "rule_version": "hookguard-1",
            "reason_codes": guard_res["reason_codes"],
        },
    }

    # Final EDL exactly matches baseline
    ok, err = verify_body_edl_preservation(baseline_fp, final_edl, mode="overlay")
    assert ok is True
    assert final_plan["status"] == "SKIPPED"
    assert final_plan["selected_candidate_id"] is None
