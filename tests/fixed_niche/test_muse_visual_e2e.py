"""Phase 6: Isolated E2E rehearsals for Muse Image Generation in OpenMontage.

Tests 3 approved in-niche topics:
1. context_memory: session memory loss across restarts
2. agent_tool_use: MCP schema mismatch
3. debugging_reliability: test regression reproduction

Plus negative cases:
4. off-niche candidate rejection
5. missing proof-bearing capture blocks production
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from lib.fixed_niche.gate import FixedNicheScopeGate, OutcomeStatus
from lib.news_visual.visual_planner import ClaimAwareVisualPlanner
from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator
from lib.news_visual.asset_resolver import resolve_visual_assets
from lib.news_visual.qa import run_news_visual_qa
from scripts.run_fixed_niche_video import FixedNicheVideoRunner


def make_test_png(width: int = 1080, height: int = 1920, color=(15, 23, 42)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("family,title,qid,canonical_url,publisher,snap_text", [
    (
        "context_memory",
        "Why coding agents lose project requirements between sessions",
        "Why do coding agents forget project rules?",
        "https://docs.anthropic.com/claude/context-window",
        "Anthropic Docs",
        (
            "Context windows in large language models represent the maximum token capacity for active working memory. "
            "When multi-turn agent conversations exceed this limit, earlier instructions are silently dropped, leading to "
            "requirement violations and broken code generation. Autonomous agents must manage context carefully."
        ),
    ),
    (
        "agent_tool_use",
        "MCP function call fails because tool JSON schema mismatches payload",
        "Why does this MCP tool call fail?",
        "https://modelcontextprotocol.io/specification/tools",
        "Model Context Protocol Docs",
        (
            "MCP tool definitions mandate strict JSON Schema parameter declarations. When autonomous client agents emit "
            "malformed tool payloads or parameter type mismatches, the MCP server rejects execution immediately with error 400. "
            "Schema validation filters are required to coerce arguments before execution."
        ),
    ),
    (
        "debugging_reliability",
        "Why AI agent patch generation introduces test regressions in CI",
        "Why do agent bug fixes cause regressions?",
        "https://docs.pytest.org/en/stable/how-to/reproducible-tests.html",
        "Pytest Documentation",
        (
            "Automated test suites in continuous integration run under isolated environment conditions. When autonomous agent "
            "patches pass isolated mock tests locally without reproducing the original defect, hidden side effects break the "
            "full test suite in CI. Reproducible regression test verification is required before merge."
        ),
    ),
])
def test_muse_e2e_rehearsals_positive_topics(
    tmp_path: Path,
    family: str,
    title: str,
    qid: str,
    canonical_url: str,
    publisher: str,
    snap_text: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Executes full offline staging, claim-aware planning, Muse image staging, and QA validation."""
    monkeypatch.setenv("AI_VISUAL_ENABLED", "1")
    monkeypatch.setenv("MUSE_GATEWAY_EXTERNAL_CALLS_ALLOWED", "1")

    project_id = f"e2e_{family}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    topic = {
        "candidate_id": project_id,
        "title": title,
        "topic_family": family,
        "viewer_question": qid,
        "canonical_url": canonical_url,
        "publisher": publisher,
        "retrieval_method": "OFFLINE_VERIFIED_PRIMARY_MIRROR",
        "content_kind": "evergreen_explainer",
        "source_snapshot": snap_text,
        "snapshot_sha256": hashlib.sha256(snap_text.encode("utf-8")).hexdigest(),
    }

    # Mock Muse Gateway tool execution
    monkeypatch.setenv("OPENMONTAGE_CACHE_DIR", str(tmp_path / "visual_cache"))
    fake_png = make_test_png()

    def mock_dispatch(dest_file, prompt, key, **kwargs):
        dest_file.write_bytes(fake_png)
        return {
            "success": True,
            "data": {
                "mime": "image/png",
                "gateway_job_id": f"job-{family}-001",
                "provider": "muse",
                "model": "muse-image",
                "submission_key": key,
                "sha256": hashlib.sha256(fake_png).hexdigest(),
            },
        }

    runner = FixedNicheVideoRunner(project_dir=project_dir, candidate_id=project_id)
    with patch.object(VisualAssetOrchestrator, "_dispatch_muse_generation", side_effect=mock_dispatch):
        stage_res = runner.build_and_stage_project(topic=topic)

    assert stage_res["status"] == "STAGED_READY"

    # Verify generated Muse image in assets
    artifacts_dir = project_dir / "artifacts"
    visuals_dir = project_dir / "assets" / "visuals"
    assert (artifacts_dir / "news_visual_plan.json").is_file()
    assert (artifacts_dir / "news_visual_assets.json").is_file()

    manifest = json.loads((artifacts_dir / "news_visual_assets.json").read_text(encoding="utf-8"))
    assert len(manifest["assets"]) >= 6

    # Verify AI art attribution in manifest
    ai_assets = [a for a in manifest["assets"] if a.get("ai_generated") is True]
    assert len(ai_assets) >= 1
    for a in ai_assets:
        assert a["provider"] == "muse"
        assert a["model"] == "muse-image"
        assert a["kind"] == "illustration"
        assert a["origin"] == "ai_generated"
        assert (project_dir / a["file"]).is_file()

    # Synthesize speech and render video
    audio_path = runner.synthesize_narration(provider="flite", voice="slt")
    assert audio_path.is_file()
    assert audio_path.stat().st_size > 1000

    render_res = runner.render()
    assert render_res["status"] == "VIDEO_READY_FOR_PRIVATE_REVIEW"
    output_mp4 = Path(render_res["rendered_mp4"])
    assert output_mp4.is_file()
    assert output_mp4.stat().st_size > 5000

    # Verify Visual QA passes
    qa_report = run_news_visual_qa(project_dir, mode="strict")
    assert qa_report["passed"] is True
    assert "PROHIBITED_AI_PROOF" not in qa_report["failure_categories"]
    assert "ASSET_UNRESOLVED" not in qa_report["failure_categories"]
    assert "VISUAL_NOT_RENDERED" not in qa_report["failure_categories"]


def test_muse_e2e_rehearsal_negative_off_niche_rejected():
    """Negative case: off-niche candidate rejected by scope gate."""
    gate = FixedNicheScopeGate()
    off_niche_cand = {
        "candidate_id": "cand_crypto_99",
        "title": "Crypto algorithmic arbitrage yield on meme coins",
        "body": "Trading bots for cryptocurrency.",
    }
    verdict = gate.evaluate_candidate(off_niche_cand)
    assert not verdict.is_eligible
    assert verdict.status == OutcomeStatus.OFF_NICHE


def test_muse_e2e_rehearsal_negative_missing_proof_blocks(tmp_path: Path):
    """Negative case: missing proof capture halts visual orchestration."""
    project_dir = tmp_path / "proj_missing_proof"
    orchestrator = VisualAssetOrchestrator()

    plan = {
        "version": "1.0",
        "project_id": "proj_missing_proof",
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "render_strategy": "authentic_capture",
                "evidence_class": "approved_source_visual",
                "fallback_policy": "block",
                "asset_ids": ["non_existent_capture"],
            }
        ],
    }
    topic = {"candidate_id": "proj_missing_proof", "topic_family": "context_memory"}

    res = orchestrator.orchestrate_plan_assets(project_dir, plan, topic)
    assert res["summary"]["blocked_missing_proof"] == 1
    assert res["beat_results"]["vb-01"]["status"] == VisualAssetOrchestrator.STATUS_BLOCKED_MISSING_PROOF
