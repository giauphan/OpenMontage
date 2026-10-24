"""Tests for Phase 5: Per-project dynamic production runner and media rendering.
Covers matrix IDs: RENDER-001, RENDER-002, RENDER-003.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import pytest

from lib.audio.narration_orchestrator import MediaCpuLock
from scripts.run_fixed_niche_video import (
    FixedNicheVideoRunner,
    render_project_composition,
)


def test_render_001_generic_runner_project_id_different_from_sample(tmp_path: Path):
    """RENDER-001: generic runner project ID different from sample -> output in correct dynamic project, no hardcoded sample assets."""
    custom_project_id = "test_agent_dynamic_99"
    project_dir = tmp_path / custom_project_id
    project_dir.mkdir(parents=True)

    runner = FixedNicheVideoRunner(
        project_dir=project_dir,
        candidate_id=custom_project_id,
        format_kind="short",
    )

    # Prepare project artifacts
    topic = {
        "candidate_id": custom_project_id,
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "viewer_question": "Why can an AI coding agent forget project rules between sessions?",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
    }
    result = runner.build_and_stage_project(topic=topic, dry_run=True)

    assert result["status"] == "STAGED_READY"
    assert (project_dir / "project.json").is_file()
    assert (project_dir / "artifacts" / "fixed_niche_scope.json").is_file()
    assert (project_dir / "artifacts" / "topic_brief.json").is_file()
    assert (project_dir / "artifacts" / "claim_ledger.json").is_file()
    assert (project_dir / "artifacts" / "news_visual_plan.json").is_file()
    assert (project_dir / "artifacts" / "video_proof_map.json").is_file()
    assert (project_dir / "assets" / "visuals").is_dir()

    # Verify no hardcoded sample paths were used
    proj_json = json.loads((project_dir / "project.json").read_text())
    assert proj_json["project_id"] == custom_project_id
    assert "us_ai_short_01" not in str(project_dir)


def test_render_002_sixty_five_to_seventy_five_seconds_duration(tmp_path: Path):
    """RENDER-002: 65–75s US pilot -> target duration within [65.0, 75.0] range."""
    custom_project_id = "test_agent_dur_72"
    project_dir = tmp_path / custom_project_id
    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=custom_project_id)
    dur = runner.get_target_duration()
    assert 65.0 <= dur <= 75.0


def test_render_003_shared_media_lock_serializes_heavy_work(tmp_path: Path):
    """RENDER-003: two concurrent jobs on Phoenix -> shared media lock serializes heavy work."""
    lock_file = tmp_path / "media_cpu.lock"

    lock1 = MediaCpuLock(lock_path=lock_file, timeout_seconds=1.0)
    lock2 = MediaCpuLock(lock_path=lock_file, timeout_seconds=1.0)

    # First acquisition succeeds
    with lock1:
        assert lock_file.exists()
        # Second acquisition with 0.1s timeout must raise TimeoutError or block
        with pytest.raises(TimeoutError):
            with MediaCpuLock(lock_path=lock_file, timeout_seconds=0.1):
                pass

    # After lock1 releases, lock2 can acquire cleanly
    with lock2:
        assert lock_file.exists()


def test_dynamic_project_isolation(tmp_path: Path):
    """Ensure Project A and Project B render to distinct output directories with no cross-contamination."""
    proj_a = tmp_path / "project_alpha"
    proj_b = tmp_path / "project_beta"

    runner_a = FixedNicheVideoRunner(project_dir=proj_a, candidate_id="cand_alpha")
    runner_b = FixedNicheVideoRunner(project_dir=proj_b, candidate_id="cand_beta")

    topic_a = {
        "candidate_id": "cand_alpha",
        "title": "Why coding agents lose context",
        "topic_family": "context_memory",
        "viewer_question": "Why does memory disappear?",
    }
    topic_b = {
        "candidate_id": "cand_beta",
        "title": "MCP schema mismatch errors",
        "topic_family": "agent_tool_use",
        "viewer_question": "Why do tool calls fail?",
    }

    res_a = runner_a.build_and_stage_project(topic=topic_a, dry_run=True)
    res_b = runner_b.build_and_stage_project(topic=topic_b, dry_run=True)

    assert res_a["status"] == "STAGED_READY"
    assert res_b["status"] == "STAGED_READY"

    # Verify assets and briefs are distinct
    brief_a = json.loads((proj_a / "artifacts" / "topic_brief.json").read_text())
    brief_b = json.loads((proj_b / "artifacts" / "topic_brief.json").read_text())
    assert brief_a["topic_id"] == "cand_alpha"
    assert brief_b["topic_id"] == "cand_beta"
    assert brief_a["topic_family"] == "context_memory"
    assert brief_b["topic_family"] == "agent_tool_use"
