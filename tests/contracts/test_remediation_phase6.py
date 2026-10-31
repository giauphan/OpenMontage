"""Phase 6 Remediation Contract Tests: YouTube Feedback & Retention Mapping.

Verifies:
- T19: Map 100-point retention curve to scene beats preserving >100% replays and real scene_ids
- T20: Graceful handling of missing/lagged YouTube Analytics with UNKNOWN status and no autonomous mutation
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.youtube_feedback.retention_mapper import (
    SceneTiming,
    RetentionPoint,
    RetentionAnalysis,
    map_retention_curve,
    generate_hypotheses_from_analysis,
)


def test_retention_curve_mapping():
    """T19: 100-point retention curve maps to scene beats, preserves >100% replays without clamping."""
    duration = 60.0
    scenes = [
        SceneTiming(scene_id="scene_001_hook", start_time=0.0, end_time=12.0, story_function="hook"),
        SceneTiming(scene_id="scene_002_evidence", start_time=12.0, end_time=30.0, story_function="evidence"),
        SceneTiming(scene_id="scene_003_analysis", start_time=30.0, end_time=48.0, story_function="analysis"),
        SceneTiming(scene_id="scene_004_takeaway", start_time=48.0, end_time=60.0, story_function="takeaway"),
    ]

    # Create 100 points: ratio 0.00 to 0.99
    # Include a replay spike at ratio 0.15 (t=9.0s, inside scene_001_hook) with watch_ratio = 1.35 (135%)
    # Include a dropoff at ratio 0.25 (t=15.0s, scene_002_evidence)
    curve = []
    for i in range(100):
        ratio = i / 100.0
        if 0.14 <= ratio <= 0.16:
            watch_ratio = 1.35  # Replay spike > 100%
        elif ratio < 0.25:
            watch_ratio = 0.90
        else:
            watch_ratio = 0.65  # Dropoff at scene 2
        curve.append((ratio, watch_ratio))

    analysis = map_retention_curve(
        duration_seconds=duration,
        retention_curve=curve,
        scenes=scenes,
        video_id="test_video_123",
        project_id="project_20261030_001",
    )

    assert analysis.status == "OK"
    assert len(analysis.points) == 100

    # Verify timestamp conversion
    point_15 = analysis.points[15]
    assert point_15.timestamp_seconds == pytest.approx(9.0)
    assert point_15.scene_id == "scene_001_hook"
    # Verify replay preservation: watch_ratio MUST NOT be clamped to 1.0!
    assert point_15.watch_ratio == 1.35
    assert any(p.watch_ratio > 1.0 for p in analysis.points), "Replay spikes > 100% must be preserved"

    # Verify scene attribution
    point_25 = analysis.points[25]
    assert point_25.timestamp_seconds == pytest.approx(15.0)
    assert point_25.scene_id == "scene_002_evidence"

    # Verify scene retention calculation
    assert "scene_001_hook" in analysis.scene_retention
    assert "scene_002_evidence" in analysis.scene_retention

    # Verify hypothesis generation
    hypotheses = generate_hypotheses_from_analysis(analysis)
    assert len(hypotheses) > 0
    # Should identify the dropoff around scene 2
    scene2_hypotheses = [h for h in hypotheses if h.scene_id == "scene_002_evidence"]
    assert len(scene2_hypotheses) > 0
    h = scene2_hypotheses[0]
    assert h.owner_status == "PENDING_REVIEW"
    assert len(h.competing_hypotheses) >= 1, "Must offer balanced competing hypotheses"
    assert h.confidence in {"LOW", "MEDIUM", "HIGH"}


def test_analytics_lag_handling():
    """T20: Missing/lagged YouTube analytics gracefully yields UNKNOWN/DATA_LAGGED, never false zeros."""
    duration = 70.0
    scenes = [
        SceneTiming(scene_id="scene_001", start_time=0.0, end_time=70.0),
    ]

    # Empty curve due to ingestion delay / suppressed rows
    analysis = map_retention_curve(
        duration_seconds=duration,
        retention_curve=[],
        scenes=scenes,
        video_id="lagged_video_456",
        project_id="project_lagged",
    )

    assert analysis.status in {"UNKNOWN", "DATA_LAGGED"}
    assert len(analysis.points) == 0
    # Missing data must NOT be fabricated as 0.0 retention
    assert analysis.scene_retention.get("scene_001") is None

    hypotheses = generate_hypotheses_from_analysis(analysis)
    assert len(hypotheses) == 0, "No causal hypotheses may be inferred from missing/lagged data"


def test_collect_youtube_feedback_cli(tmp_path: Path):
    """Verifies scripts/collect_youtube_feedback.py end-to-end with simulated project and curve."""
    import subprocess
    import sys

    # Set up project dir with visual_plan.json
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    visual_plan = {
        "scenes": [
            {"scene_id": "sc1", "start_time": 0.0, "end_time": 10.0, "story_function": "hook"},
            {"scene_id": "sc2", "start_time": 10.0, "end_time": 30.0, "story_function": "proof"},
        ]
    }
    (project_dir / "visual_plan.json").write_text(json.dumps(visual_plan), encoding="utf-8")

    # Set up retention curve file
    curve_file = tmp_path / "curve.json"
    curve_data = [
        {"elapsedVideoTimeRatio": 0.0, "audienceWatchRatio": 1.0},
        {"elapsedVideoTimeRatio": 0.2, "audienceWatchRatio": 1.15},  # Replay spike
        {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": 0.70},  # Dropoff
    ]
    curve_file.write_text(json.dumps(curve_data), encoding="utf-8")

    out_file = tmp_path / "feedback_report.json"
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "collect_youtube_feedback.py"

    cmd = [
        sys.executable,
        str(script),
        "--project-dir", str(project_dir),
        "--video-id", "test_vid_xyz",
        "--retention-curve-file", str(curve_file),
        "--output-json", str(out_file),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
    assert res.returncode == 0, f"Script failed: {res.stderr}"

    assert out_file.is_file()
    report = json.loads(out_file.read_text(encoding="utf-8"))
    assert report["status"] == "OK"
    assert report["video_id"] == "test_vid_xyz"
    assert report["points_count"] == 3
    assert report["spikes_count"] >= 1
    assert "sc1" in report["scene_retention"]

