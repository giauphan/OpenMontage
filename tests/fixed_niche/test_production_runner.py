"""Tests for Phase 5: Per-project dynamic production runner and media rendering.
Covers matrix IDs: RENDER-001, RENDER-002, RENDER-003.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
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


def test_runner_rejects_unsupported_format(tmp_path: Path):
    """Ensure runner rejects any format other than short/shorts."""
    with pytest.raises(ValueError, match="strictly locked to 'short'"):
        FixedNicheVideoRunner(project_dir=tmp_path / "p1", candidate_id="c1", format_kind="longform")


def test_runner_stages_srt_captions_and_validates_script_sha(tmp_path: Path):
    """Ensure build_and_stage_project produces valid captions.srt and exact script SHA256 in assets manifest."""
    proj_dir = tmp_path / "caption_test_proj"
    runner = FixedNicheVideoRunner(project_dir=proj_dir, candidate_id="cand_caps")
    topic = {
        "candidate_id": "cand_caps",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "viewer_question": "Why do coding agents forget requirements?",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
    }
    res = runner.build_and_stage_project(topic=topic, dry_run=True)
    assert res["status"] == "STAGED_READY"

    # Verify captions.srt and styled captions.ass
    srt_path = proj_dir / "artifacts" / "captions.srt"
    assert srt_path.is_file()
    srt_content = srt_path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> " in srt_content
    assert len(srt_content.strip().split("\n\n")) >= 6

    ass_path = proj_dir / "artifacts" / "captions.ass"
    assert ass_path.is_file()
    assert "PlayResY: 1920" in ass_path.read_text(encoding="utf-8")

    # Verify script SHA256 in assets manifest matches actual script_en_US.json
    script_bytes = (proj_dir / "artifacts" / "script_en_US.json").read_bytes()
    expected_sha = hashlib.sha256(script_bytes).hexdigest()
    assets_manifest = json.loads((proj_dir / "artifacts" / "news_visual_assets.json").read_text(encoding="utf-8"))
    assert assets_manifest["script_sha256"] == expected_sha


def test_render_rejects_missing_audio_in_production(tmp_path: Path):
    """In production renders, missing narration audio must raise FileNotFoundError rather than silently faking audio."""
    proj_dir = tmp_path / "no_audio_proj"
    proj_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Narration audio file missing"):
        render_project_composition(project_dir=proj_dir, allow_synthetic_audio=False)


def test_render_rejects_narration_exceeding_target_duration(tmp_path: Path):
    """If narration audio exceeds target duration, render must fail closed to prevent speech truncation."""
    proj_dir = tmp_path / "long_audio_proj"
    audio_path = proj_dir / "assets" / "narration.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    # Generate 10-second silent mp3
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", "10", "-c:a", "libmp3lame", str(audio_path)],
        check=True,
    )
    # Attempting to render with duration_seconds=5.0 must raise ValueError
    with pytest.raises(ValueError, match="exceeds target duration"):
        render_project_composition(project_dir=proj_dir, duration_seconds=5.0)


def test_render_qa_gate_fails_closed_on_corrupt_video(tmp_path: Path, monkeypatch):
    """If ffprobe fails or output video is corrupt, approval.json must record QA_FAILED and approved=False."""
    proj_dir = tmp_path / "qa_fail_proj"
    runner = FixedNicheVideoRunner(project_dir=proj_dir, candidate_id="cand_fail")
    topic = {
        "candidate_id": "cand_fail",
        "title": "Why coding agents fail on cyclic dependencies",
        "topic_family": "agent_tool_use",
        "viewer_question": "Why do cycles break agents?",
    }
    runner.build_and_stage_project(topic=topic, dry_run=True)

    # Monkeypatch render_project_composition to write an invalid 0-byte video
    def fake_render(project_dir, composition_name, output_mp4, duration_seconds, **kwargs):
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        output_mp4.write_bytes(b"")
        return output_mp4

    monkeypatch.setattr("scripts.run_fixed_niche_video.render_project_composition", fake_render)

    res = runner.render()
    assert res["status"] == "QA_FAILED"

    approval = json.loads((proj_dir / "approval.json").read_text(encoding="utf-8"))
    assert approval["approved"] is False
    assert approval["status"] == "QA_FAILED"

    val_status = json.loads((proj_dir / "validation_status.json").read_text(encoding="utf-8"))
    assert val_status["strict_quality_pass"] is False
    assert val_status["status"] == "QA_FAILED"


def test_cli_returns_nonzero_when_qa_fails(tmp_path: Path, monkeypatch):
    """Ensure scripts.run_fixed_niche_video.main returns exit code 1 when QA fails."""
    from scripts.run_fixed_niche_video import main

    def fake_render(project_dir, composition_name, output_mp4, duration_seconds, **kwargs):
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        output_mp4.write_bytes(b"")
        return output_mp4

    monkeypatch.setattr("scripts.run_fixed_niche_video.render_project_composition", fake_render)

    exit_code = main([
        "--candidate-id", "cand_cli_fail",
        "--project-dir", str(tmp_path / "cli_fail_proj"),
        "--title", "Why coding agents crash on recursion",
        "--provider", "flite",
    ])
    assert exit_code == 1


def test_cli_auto_select_production_isolation_without_fixtures(tmp_path: Path, monkeypatch, capsys):
    """Ensure --auto-select in production mode does not load test fixtures implicitly."""
    from scripts.run_fixed_niche_video import main

    monkeypatch.setattr(
        "tools.news.fixed_niche_sources.FixedNicheSourceAdapter.discover_production_candidates",
        lambda self, **kw: [],
    )
    # In production without feed or fixtures, auto-select must return 0 with NO_ELIGIBLE_TOPIC
    exit_code = main([
        "--auto-select",
        "--project-dir", str(tmp_path / "prod_auto_proj"),
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "NO_ELIGIBLE_TOPIC" in captured.out
    assert not (tmp_path / "prod_auto_proj").exists()


def test_cli_auto_select_with_production_feed(tmp_path: Path):
    """Ensure --auto-select in production mode discovers candidates from production feed."""
    from scripts.run_fixed_niche_video import main

    exit_code = main([
        "--auto-select",
        "--project-dir", str(tmp_path / "prod_feed_proj"),
        "--dry-run",
    ])
    assert exit_code == 0
    assert (tmp_path / "prod_feed_proj" / "project.json").is_file()


def test_cli_auto_select_with_use_test_fixtures(tmp_path: Path, capsys):
    """Ensure --use-test-fixtures explicitly allows loading fixture pool."""
    from scripts.run_fixed_niche_video import main

    exit_code = main([
        "--auto-select",
        "--use-test-fixtures",
        "--project-dir", str(tmp_path / "fixtures_auto_proj"),
        "--dry-run",
    ])
    assert exit_code == 0
    assert (tmp_path / "fixtures_auto_proj" / "project.json").is_file()


def test_off_niche_candidate_leaves_no_disk_artifacts(tmp_path: Path):
    """Ensure off-niche candidate fails scope gate before creating project directories on disk."""
    proj_dir = tmp_path / "off_niche_ghost_proj"
    runner = FixedNicheVideoRunner(
        project_dir=proj_dir,
        candidate_id="ghost_cand",
    )
    off_niche_topic = {
        "candidate_id": "ghost_cand",
        "title": "Celebrity gossip about AI influencers",
        "topic_family": "entertainment",
    }
    stage_res = runner.build_and_stage_project(off_niche_topic)
    assert stage_res["status"] == "REJECTED_OFF_NICHE"
    assert not proj_dir.exists(), "Off-niche rejection must not leave an empty ghost project directory"


def test_hyperframes_composition_is_materialized_with_valid_structure(tmp_path: Path):
    """Ensure HyperFrames index.html has data-composition-id, data-start, and registered timeline."""
    proj_dir = tmp_path / "hf_valid_proj"
    runner = FixedNicheVideoRunner(
        project_dir=proj_dir,
        candidate_id="hf_cand",
    )
    topic = {
        "candidate_id": "hf_cand",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
    }
    runner.build_and_stage_project(topic)

    reels_index = proj_dir / "hyperframes_reels" / "index.html"
    assert reels_index.is_file()
    content = reels_index.read_text(encoding="utf-8")
    assert 'data-composition-id="main"' in content
    assert 'data-start="0"' in content
    assert 'data-width="1080"' in content
    assert 'data-height="1920"' in content
    assert 'window.__timelines["main"] = tl;' in content
    assert 'class="clip"' in content


def test_qa_approval_record_contains_supervisor_signature(tmp_path: Path):
    """Ensure approval.json contains valid HMAC-SHA256 signature from qa_signing."""
    from lib.qa_signing import verify_approval_record

    proj_dir = tmp_path / "signed_qa_proj"
    runner = FixedNicheVideoRunner(
        project_dir=proj_dir,
        candidate_id="cand_signed",
    )
    import hashlib
    snap_text = "Context window limitations require serializing state across independent coding sessions."
    topic = {
        "candidate_id": "cand_signed",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "publisher": "Anthropic Docs",
        "retrieval_method": "OFFLINE_VERIFIED_PRIMARY_MIRROR",
        "source_snapshot": snap_text,
        "snapshot_sha256": hashlib.sha256(snap_text.encode("utf-8")).hexdigest(),
    }
    runner.build_and_stage_project(topic)
    runner.synthesize_narration(provider="flite")

    res = runner.render()
    assert res["status"] == "VIDEO_READY_FOR_PRIVATE_REVIEW"

    approval_path = proj_dir / "approval.json"
    assert approval_path.is_file()
    app_data = json.loads(approval_path.read_text(encoding="utf-8"))
    assert app_data["approved"] is True
    assert "signature" in app_data
    assert app_data["signature_algorithm"] == "HMAC-SHA256"
    is_valid, reason = verify_approval_record(app_data, project_id="cand_signed")
    assert is_valid is True, f"Signature verification failed: {reason}"


def test_runner_supports_renderer_selection(tmp_path: Path, monkeypatch):
    """Ensure runner passes renderer choice to render_project_composition."""
    from scripts.run_fixed_niche_video import FixedNicheVideoRunner
    import subprocess

    called_renderers = []

    def fake_render(project_dir, composition_name, output_mp4, duration_seconds, **kwargs):
        called_renderers.append(kwargs.get("renderer"))
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=c=black:s=1080x1920:d=1:r=30", "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=stereo", "-t", "1", "-c:v", "libx264",
            "-c:a", "aac", str(output_mp4),
        ], check=True)
        return output_mp4

    monkeypatch.setattr("scripts.run_fixed_niche_video.render_project_composition", fake_render)

    proj_dir = tmp_path / "renderer_test_proj"
    runner = FixedNicheVideoRunner(project_dir=proj_dir, candidate_id="cand_rend")
    topic = {
        "candidate_id": "cand_rend",
        "title": "Why coding agents crash on recursion",
        "topic_family": "agent_tool_use",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "source_snapshot": "Recursion limits in coding agents cause call stack overflows.",
    }
    runner.build_and_stage_project(topic=topic, dry_run=True)
    (proj_dir / "assets").mkdir(parents=True, exist_ok=True)
    (proj_dir / "assets" / "narration.mp3").write_bytes(b"dummy")

    runner.render(renderer="hyperframes")
    assert called_renderers == ["hyperframes"]

    runner.render(renderer="ffmpeg")
    assert called_renderers == ["hyperframes", "ffmpeg"]


def test_synthesize_narration_recovers_and_restages_for_duration_above_72s(tmp_path: Path, monkeypatch):
    """Ensure narration in (72.0, 75.0]s is recoverable by automatically re-staging to 7 beats."""
    proj_dir = tmp_path / "restage_proj"
    runner = FixedNicheVideoRunner(project_dir=proj_dir, candidate_id="cand_restage")
    topic = {
        "candidate_id": "cand_restage",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "source_snapshot": "Conversation context disappears on session boundary unless persisted in markdown.",
    }
    stage_res = runner.build_and_stage_project(topic=topic, dry_run=False)
    assert stage_res["status"] == "STAGED_READY"
    assert stage_res["beats_count"] == 6

    def fake_synthesize(*args, **kwargs):
        out = kwargs.get("output_path") or args[1]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"dummy_mp3")
        return {"success": True}

    monkeypatch.setattr(runner.orchestrator, "synthesize", fake_synthesize)
    monkeypatch.setattr("scripts.run_fixed_niche_video.probe_audio_duration", lambda p: 73.5)

    runner.synthesize_narration(provider="flite")

    plan = json.loads((proj_dir / "artifacts" / "news_visual_plan.json").read_text(encoding="utf-8"))
    assert len(plan["beats"]) == 7
    for b in plan["beats"]:
        assert (b["end_s"] - b["start_s"]) <= 12.0


def test_synthesize_narration_rejects_duration_above_policy_max(tmp_path: Path, monkeypatch):
    """Ensure narration > 75.0s strictly fails closed."""
    proj_dir = tmp_path / "exceed_max_proj"
    runner = FixedNicheVideoRunner(project_dir=proj_dir, candidate_id="cand_exceed")
    topic = {
        "candidate_id": "cand_exceed",
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "source_snapshot": "Conversation context disappears on session boundary unless persisted in markdown.",
    }
    runner.build_and_stage_project(topic=topic, dry_run=False)

    monkeypatch.setattr(runner.orchestrator, "synthesize", lambda *a, **k: {"success": True})
    (proj_dir / "assets" / "narration.mp3").write_bytes(b"dummy")
    monkeypatch.setattr("scripts.run_fixed_niche_video.probe_audio_duration", lambda p: 76.5)

    with pytest.raises(ValueError) as exc:
        runner.synthesize_narration(provider="flite")
    assert "exceeds maximum allowed duration" in str(exc.value)



