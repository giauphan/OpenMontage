"""Tests for Phase 7: Three independent offline E2E rehearsals (A, B, C) and private canary safety.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from lib.fixed_niche.policy import load_locked_policy, OutcomeStatus
from lib.fixed_niche.gate import FixedNicheScopeGate
from lib.fixed_niche.topic_selector import FixedNicheTopicSelector
from lib.fixed_niche.research import FixedNicheResearcher, DemoExecutionProtocol
from lib.fixed_niche.qa import FixedNicheQAValidator
from scripts.run_fixed_niche_video import FixedNicheVideoRunner


def test_rehearsal_a_evergreen_concept_video_e2e(tmp_path: Path):
    """Rehearsal A: Passing evergreen concept video through full offline production pipeline."""
    import hashlib
    project_id = "rehearsal_a_context_lifecycle"
    project_dir = tmp_path / project_id

    snap_text = "Context window limitations require durable disk file persistence across independent agent sessions."
    topic = {
        "candidate_id": project_id,
        "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory",
        "viewer_question": "Why can an AI coding agent forget project rules between sessions?",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "publisher": "Anthropic Docs",
        "content_kind": "evergreen_explainer",
        "source_snapshot": snap_text,
        "snapshot_sha256": hashlib.sha256(snap_text.encode("utf-8")).hexdigest(),
    }

    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=project_id)

    # 1. Build and stage
    stage_res = runner.build_and_stage_project(topic=topic)
    assert stage_res["status"] == "STAGED_READY"
    assert (project_dir / "artifacts" / "fixed_niche_scope.json").is_file()
    assert (project_dir / "artifacts" / "topic_brief.json").is_file()
    assert (project_dir / "artifacts" / "claim_ledger.json").is_file()
    assert (project_dir / "artifacts" / "news_visual_plan.json").is_file()
    assert (project_dir / "artifacts" / "video_proof_map.json").is_file()

    # 2. Voice synthesis
    audio_path = runner.synthesize_narration(provider="flite", voice="slt")
    assert audio_path.is_file()
    assert audio_path.stat().st_size > 1000

    # 3. Render video
    render_res = runner.render()
    assert render_res["status"] == "VIDEO_READY_FOR_PRIVATE_REVIEW"
    output_mp4 = Path(render_res["rendered_mp4"])
    assert output_mp4.is_file()
    assert output_mp4.stat().st_size > 5000

    # 4. Verify sampled frames
    frames_dir = project_dir / "renders" / "frame_samples"
    assert frames_dir.is_dir()
    sampled_frames = list(frames_dir.glob("*.png"))
    assert len(sampled_frames) >= 4

    # 5. Independent QA audit
    qa_validator = FixedNicheQAValidator()
    qa_report = qa_validator.audit_fixed_niche_deliverable(project_dir, expected_duration=72.0)
    assert qa_report["strict_quality_pass"] is True
    assert qa_report["blockers_count"] == 0

    # 6. Cryptographic approval check
    assert qa_validator.verify_audio_and_release_integrity(project_dir) is True


def test_rehearsal_b_reproduced_demo_experiment_video_e2e(tmp_path: Path):
    """Rehearsal B: Passing genuine mock-experiment video with verified sandbox demo results."""
    project_id = "rehearsal_b_mcp_schema_repro"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    # 1. Execute isolated sandbox reproduction
    demo_protocol = DemoExecutionProtocol(working_dir=project_dir)
    demo_cmd = 'python3 -c \'import json; payload={"cmd": "ls"}; schema={"required": ["command"]}; print("Schema validation failed: missing command") if "command" not in payload else print("ok")\''
    demo_res = demo_protocol.run_isolated_command(command=demo_cmd)
    assert demo_res["exit_code"] == 0
    assert "Schema validation failed" in demo_res["stdout"]

    # Write demo artifacts
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "demo_protocol.json").write_text(json.dumps({"command": demo_cmd}, indent=2))
    (artifacts_dir / "demo_results.json").write_text(json.dumps(demo_res, indent=2))

    demo_snap = "Model Context Protocol JSON-RPC specification requires tool call parameters to validate against declared schema."
    topic = {
        "candidate_id": project_id,
        "title": "MCP function call fails because tool JSON schema mismatches payload",
        "topic_family": "agent_tool_use",
        "viewer_question": "Why does this MCP tool call fail?",
        "canonical_url": "https://modelcontextprotocol.io/specification/tools",
        "publisher": "MCP Specification",
        "content_kind": "reproduced_demo",
        "source_snapshot": demo_snap,
        "snapshot_sha256": hashlib.sha256(demo_snap.encode("utf-8")).hexdigest(),
    }

    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=project_id)
    stage_res = runner.build_and_stage_project(topic=topic)
    assert stage_res["status"] == "STAGED_READY"

    # Verify script claims with demo results present
    script_data = json.loads((artifacts_dir / "script_en_US.json").read_text())
    script_data["sections"][0]["narration"] = "In our lab test, we verified the tool schema mismatch."
    researcher = FixedNicheResearcher()
    valid, reason = researcher.verify_script_claims(
        script_data,
        claim_ledger=[{"claim_id": "C001"}],
        demo_results=demo_res,
    )
    assert valid is True

    # Render and audit
    runner.synthesize_narration(provider="flite", voice="slt")
    render_res = runner.render()
    assert render_res["status"] == "VIDEO_READY_FOR_PRIVATE_REVIEW"

    qa_validator = FixedNicheQAValidator()
    qa_report = qa_validator.audit_fixed_niche_deliverable(project_dir)
    assert qa_report["strict_quality_pass"] is True


def test_rehearsal_c_rejected_off_niche_no_topic_day_e2e(tmp_path: Path):
    """Rehearsal C: Rejected off-niche/no-topic day yields NO_ELIGIBLE_TOPIC with zero side-effects."""
    off_niche_pool = [
        {"id": "cand_crypto_01", "title": "Buy bitcoin now with automated AI trading bot"},
        {"id": "cand_celeb_02", "title": "Celebrity tech billionaire luxury vacation photos"},
        {"id": "cand_phone_03", "title": "New smartphone camera review with AI zoom"},
    ]

    gate = FixedNicheScopeGate()
    eligible_candidates = [c for c in off_niche_pool if gate.evaluate_candidate(c).is_eligible]
    assert len(eligible_candidates) == 0

    selector = FixedNicheTopicSelector()
    selection_res = selector.select_topic(eligible_candidates)

    assert selection_res["status"] == OutcomeStatus.NO_ELIGIBLE_TOPIC.value
    assert selection_res.get("selected_candidate_id") is None
    assert selection_res.get("projects_created") == 0

    # Assert zero project directories created in tmp_path
    created_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(created_dirs) == 0


@pytest.mark.parametrize("cand_idx", [0, 1, 2])
def test_ai_director_pipeline_full_dynamic_8_stages_e2e(tmp_path: Path, cand_idx: int):
    """End-to-End Test: Full 8-stage dynamic AI Director pipeline across 3 independent production topics."""
    from tools.news.fixed_niche_sources import FixedNicheSourceAdapter
    from scripts.run_us_ai_director_pipeline import run_us_ai_director_pipeline

    adapter = FixedNicheSourceAdapter()
    candidates = adapter.discover_production_candidates()
    assert len(candidates) >= 3, "Insufficient production candidates found"
    cand = candidates[cand_idx]

    project_dir = tmp_path / f"dynamic_director_short_{cand_idx}"
    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=cand.get("id", f"cand_{cand_idx}"), format_kind="short")
    staged = runner.build_and_stage_project(topic=cand)
    assert staged["status"] == "STAGED_READY"

    # Verify topic_family correctly preserved from feed candidate
    brief = json.loads((project_dir / "artifacts" / "topic_brief.json").read_text(encoding="utf-8"))
    assert brief.get("topic_family") == cand.get("topic_family")

    # Execute all 8 stages
    pipeline_res = run_us_ai_director_pipeline(
        project_dir=project_dir,
        format_type="short",
        render_mode="full",
    )

    assert pipeline_res["status"] == "SUCCESS"
    assert len(pipeline_res["stages"]) == 8
    for stage_info in pipeline_res["stages"]:
        assert stage_info["status"] == "PASS", f"Stage {stage_info['stage']} failed: {stage_info.get('details')}"

    # Verify deliverable artifacts
    renders_dir = project_dir / "renders"
    video_path = renders_dir / "final_short_en_US_9x16.mp4"
    assert video_path.is_file()
    assert video_path.stat().st_size > 50000

    frame_samples = list((renders_dir / "frame_samples").glob("*.png"))
    assert len(frame_samples) >= 3

    assert (project_dir / "artifacts" / "captions_en_US.srt").is_file()
    assert (project_dir / "assets" / "narration.mp3").is_file()
    assert (project_dir / "artifacts" / "video_proof_map.json").is_file()

    # Verify cryptographically signed supervisor approval
    approval_path = project_dir / "approval.json"
    assert approval_path.is_file()
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    assert approval.get("status", "").lower() == "approved"
    assert "signature" in approval and len(approval["signature"]) == 64


def test_ai_director_pipeline_rejects_unverified_claim_negative(tmp_path: Path):
    """Negative Test: AI Director Stage 3 rejects unverified/unapproved claims."""
    from tools.news.fixed_niche_sources import FixedNicheSourceAdapter
    from scripts.run_us_ai_director_pipeline import stage_3_editorial_grounding, StageExecutionError

    adapter = FixedNicheSourceAdapter()
    cand = adapter.discover_production_candidates()[0]

    project_dir = tmp_path / "negative_unverified_claim"
    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=cand.get("id", "cand_01"), format_kind="short")
    runner.build_and_stage_project(topic=cand)

    # 1. Corrupt verdict to REJECTED with verified confidence
    ledger_path = project_dir / "artifacts" / "claim_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["claims"][0]["verdict"] = "REJECTED"
    ledger["claims"][0]["confidence"] = "verified"
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    with pytest.raises(StageExecutionError, match="Stage 3 failed: claim C001 has unapproved verdict 'REJECTED'"):
        stage_3_editorial_grounding(project_dir)

    # 2. Corrupt confidence to unverified with APPROVED verdict
    ledger["claims"][0]["verdict"] = "APPROVED"
    ledger["claims"][0]["confidence"] = "unverified"
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    with pytest.raises(StageExecutionError, match="Stage 3 failed: claim C001 has unverified confidence 'unverified'"):
        stage_3_editorial_grounding(project_dir)


def test_ai_director_pipeline_rejects_tampered_snapshot_negative(tmp_path: Path):
    """Negative Test: AI Director Stage 1 rejects tampered or mismatched source snapshot."""
    from tools.news.fixed_niche_sources import FixedNicheSourceAdapter
    from scripts.run_us_ai_director_pipeline import stage_1_research_and_sources, StageExecutionError

    adapter = FixedNicheSourceAdapter()
    cand = adapter.discover_production_candidates()[0]

    project_dir = tmp_path / "negative_tampered_snapshot"
    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=cand.get("id", "cand_01"), format_kind="short")
    runner.build_and_stage_project(topic=cand)

    # Tamper with snapshot file text
    snap_path = project_dir / "artifacts" / "source_snapshot.txt"
    snap_path.write_text("Tampered snapshot content invalidating sha256 digest.", encoding="utf-8")

    with pytest.raises(StageExecutionError, match="Stage 1 failed: claim C001 snapshot SHA mismatch"):
        stage_1_research_and_sources(project_dir)


def test_ai_director_pipeline_rejects_unsubstantiated_numeric_claim_negative(tmp_path: Path):
    """Negative Test: AI Director Stage 3 rejects numbers in script spans not substantiated by excerpt."""
    from tools.news.fixed_niche_sources import FixedNicheSourceAdapter
    from scripts.run_us_ai_director_pipeline import stage_3_editorial_grounding, StageExecutionError

    adapter = FixedNicheSourceAdapter()
    cand = adapter.discover_production_candidates()[0]

    project_dir = tmp_path / "negative_numeric_grounding"
    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=cand.get("id", "cand_01"), format_kind="short")
    runner.build_and_stage_project(topic=cand)

    ledger_path = project_dir / "artifacts" / "claim_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    # Introduce an unsubstantiated number into script_spans
    ledger["claims"][0]["script_spans"] = ["Autonomous coding agent failed in 99.9% of production invocations."]
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    # Invalidate script text with the same statement
    script_path = project_dir / "artifacts" / "script_en_US.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    script["sections"][0]["narration"] = "Autonomous coding agent failed in 99.9% of production invocations."
    script_path.write_text(json.dumps(script, indent=2), encoding="utf-8")

    with pytest.raises(StageExecutionError, match="not substantiated by excerpt"):
        stage_3_editorial_grounding(project_dir)

