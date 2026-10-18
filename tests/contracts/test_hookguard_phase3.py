"""Tests for HookGuard Phase 3: Overlay-only integration, runtime adapters, and pre/post render guards."""

from __future__ import annotations

import copy
import pytest
from pathlib import Path

from lib.hook_guard.adapters import get_adapter
from lib.hook_guard.adapters.remotion import RemotionHookAdapter
from lib.hook_guard.canonical_edl import compute_body_edl_fingerprint, verify_body_edl_preservation
from lib.hook_guard.post_render import verify_post_render
from tools.analysis.hook_guard import HookGuard
from tools.tool_registry import ToolRegistry


def sample_clip_edl():
    return {
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
        "cuts": [
            {
                "id": "cut-1",
                "source": "assets/clip.mp4",
                "in_seconds": 0.0,
                "out_seconds": 8.0,
                "speed": 1.0,
                "layer": "primary",
            }
        ],
        "audio": {
            "narration": {
                "segments": [
                    {"asset_id": "narr-1", "start_seconds": 0.0, "end_seconds": 7.5}
                ]
            }
        },
        "overlays": [],
    }


def sample_candidate():
    return {
        "id": "c1",
        "intent": "problem_first",
        "mode": "overlay_text",
        "text": "The one cut that ruins video pacing",
        "window": {"start_seconds": 0.0, "end_seconds": 2.5},
        "evidence": [
            {
                "kind": "transcript",
                "source_id": "clip.mp4",
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "claim": "The one cut that ruins video pacing",
            }
        ],
    }


# --- Adapter Tests ---

def test_remotion_adapter_materializes_asset(tmp_path):
    adapter = RemotionHookAdapter()
    cand = sample_candidate()
    asset = adapter.materialize_asset(cand, tmp_path, video_metadata={"resolution": "1080x1920"})

    assert asset["id"] == "hook_c1"
    assert asset["type"] == "image"
    assert Path(asset["path"]).is_file()
    assert Path(asset["path"]).stat().st_size > 0
    assert asset["metadata"]["is_hook"] is True


def test_remotion_adapter_preserves_body_edl(tmp_path):
    adapter = RemotionHookAdapter()
    cand = sample_candidate()
    edl = sample_clip_edl()
    baseline_fp = compute_body_edl_fingerprint(edl)

    asset = adapter.materialize_asset(cand, tmp_path)
    mutated = adapter.apply_overlay(edl, cand, asset)

    # Overlays array should now have the hook
    assert len(mutated["overlays"]) == 1
    assert mutated["overlays"][0]["asset_id"] == "hook_c1"

    # Strict invariant: canonical body cuts and audio must be identical
    ok, err = verify_body_edl_preservation(baseline_fp, mutated, mode="overlay")
    assert ok is True
    assert err == ""

    # Rollback removes hook overlay and leaves EDL pristine
    rolled_back = adapter.rollback_overlay(mutated)
    assert len(rolled_back["overlays"]) == 0
    assert rolled_back["cuts"] == edl["cuts"]
    assert rolled_back["audio"] == edl["audio"]


def test_adapter_factory_returns_expected_adapters():
    rem = get_adapter("remotion")
    assert isinstance(rem, RemotionHookAdapter)
    ff = get_adapter("ffmpeg")
    assert ff is not None
    hf = get_adapter("hyperframes")
    assert hf is not None

    with pytest.raises(ValueError):
        get_adapter("unsupported_engine")


# --- HookGuard Tool Tests ---

def test_hook_guard_tool_discovery():
    registry = ToolRegistry()
    registry.discover()
    guard = registry.get("hook_guard")
    assert guard is not None
    assert guard.name == "hook_guard"


def test_hook_guard_evaluates_clean_overlay():
    guard = HookGuard()
    edl = sample_clip_edl()
    baseline_sha = compute_body_edl_fingerprint(edl)
    cand = sample_candidate()

    res = guard.execute({
        "candidate": cand,
        "baseline_body_edl_sha256": baseline_sha,
        "mutated_edl": edl,
        "render_runtime": "remotion",
        "video_duration": 8.0,
        "policy": {"enabled": True, "mode": "auto"},
    })

    assert res.success is True
    guard_res = res.data["guard_result"]
    assert guard_res["status"] == "PASS"
    assert "PASS_CLEAN" in guard_res["reason_codes"]


def test_hook_guard_rejects_mutated_body_cuts():
    guard = HookGuard()
    edl = sample_clip_edl()
    baseline_sha = compute_body_edl_fingerprint(edl)
    cand = sample_candidate()

    # Mutate cut
    corrupted_edl = copy.deepcopy(edl)
    corrupted_edl["cuts"][0]["in_seconds"] = 1.0

    res = guard.execute({
        "candidate": cand,
        "baseline_body_edl_sha256": baseline_sha,
        "mutated_edl": corrupted_edl,
        "render_runtime": "remotion",
        "video_duration": 8.0,
        "policy": {"enabled": True, "mode": "auto"},
    })

    assert res.success is True
    guard_res = res.data["guard_result"]
    assert guard_res["status"] == "REJECTED"
    assert "REJECTED_BODY_EDL_MUTATED" in guard_res["reason_codes"]


def test_hook_guard_rejects_unsupported_runtime_feature():
    guard = HookGuard()
    edl = sample_clip_edl()
    baseline_sha = compute_body_edl_fingerprint(edl)
    cand = sample_candidate()
    cand["mode"] = "unsupported_vfx"

    res = guard.execute({
        "candidate": cand,
        "baseline_body_edl_sha256": baseline_sha,
        "render_runtime": "ffmpeg",
        "policy": {"enabled": True, "mode": "auto"},
    })

    assert res.success is True
    guard_res = res.data["guard_result"]
    assert guard_res["status"] == "SKIPPED"
    assert "SKIPPED_RUNTIME_UNSUPPORTED" in guard_res["reason_codes"]


# --- Post-Render Verification Tests ---

def test_post_render_detects_duration_mismatch(tmp_path, monkeypatch):
    edl = sample_clip_edl()
    baseline_sha = compute_body_edl_fingerprint(edl)
    fake_video = tmp_path / "rendered.mp4"
    fake_video.write_bytes(b"dummy_content")

    # Mock probe to return duration 10.0 when expected is 8.0
    import lib.hook_guard.post_render as pr
    monkeypatch.setattr(pr, "probe_rendered_video", lambda p: {
        "duration_seconds": 10.0,
        "size_bytes": 1000,
        "has_video": True,
        "has_audio": True,
    })
    monkeypatch.setattr(pr, "check_first_seconds_black", lambda p: False)

    ok, reason, diag = verify_post_render(
        fake_video,
        expected_duration=8.0,
        baseline_body_edl_sha256=baseline_sha,
        mutated_edl=edl,
        tolerance_seconds=0.5,
    )

    assert ok is False
    assert reason == "REJECTED_POST_RENDER_FAILED"
    assert "differs from expected" in diag["error"]


def test_post_render_passes_on_valid_output(tmp_path, monkeypatch):
    edl = sample_clip_edl()
    baseline_sha = compute_body_edl_fingerprint(edl)
    fake_video = tmp_path / "rendered.mp4"
    fake_video.write_bytes(b"dummy_content")

    import lib.hook_guard.post_render as pr
    monkeypatch.setattr(pr, "probe_rendered_video", lambda p: {
        "duration_seconds": 8.05,
        "size_bytes": 10000,
        "has_video": True,
        "has_audio": True,
    })
    monkeypatch.setattr(pr, "check_first_seconds_black", lambda p: False)

    ok, reason, diag = verify_post_render(
        fake_video,
        expected_duration=8.0,
        baseline_body_edl_sha256=baseline_sha,
        mutated_edl=edl,
        tolerance_seconds=0.5,
    )

    assert ok is True
    assert reason is None
    assert diag["status"] == "VERIFIED"
