"""Phase 2 Remediation Contract Tests: Context-Aware Visual Director and Canonical Asset Contract.

Verifies:
- T06: Contextual claim-to-scene mapping (no modulo fallback)
- T07: Fail when authentic capture exists on disk but is omitted from HTML (binding check)
- T08: Fail when wrong visual is shown under claim (semantic mapping)
- T09: PROOF_NOT_AUTHENTIC: Muse AI illustration cannot replace proof
- T10: Meaningful SVG fallback when AI visual is disabled or quota exhausted
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from lib.news_visual.visual_planner import ClaimAwareVisualPlanner
from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator
from lib.news_visual.qa import run_news_visual_qa


def test_semantic_claim_scene_assignment():
    """T06: Claims are assigned to beats semantically by section_id/statement, not modulo."""
    planner = ClaimAwareVisualPlanner()
    sections = [
        {"id": "sec_0", "start_seconds": 0.0, "end_seconds": 10.0, "text": "Specific benchmark shows 45% recovery mentioned early."},
        {"id": "sec_1", "start_seconds": 10.0, "end_seconds": 22.0, "text": "Transition discussing architecture."},
        {"id": "sec_2", "start_seconds": 22.0, "end_seconds": 34.0, "text": "Specific benchmark shows 45% recovery."},
    ]
    # Only sec_2 has a verified claim in ledger
    claim_ledger = [
        {
            "claim_id": "C001",
            "section_id": "sec_2",
            "statement": "Specific benchmark shows 45% recovery.",
            "verdict": "APPROVED",
        }
    ]

    beats = planner._assemble_beats(
        project_id="test_p06",
        sections=sections,
        claim_ledger=claim_ledger,
        existing_captures=[],
    )

    assert len(beats) == 3
    # Beat 0 must NOT steal C001 despite matching text because C001 has explicit section_id="sec_2"
    assert beats[0].claim_ids == [], f"Beat 0 should have no claim, got {beats[0].claim_ids}"
    assert beats[1].claim_ids == [], f"Beat 1 should have no claim, got {beats[1].claim_ids}"
    assert beats[2].claim_ids == ["C001"], f"Beat 2 must have C001, got {beats[2].claim_ids}"


def test_muse_cannot_masquerade_as_proof(tmp_path: Path):
    """T09: When authentic capture is missing for proof beat, Muse illustration is NOT used as proof."""
    orchestrator = VisualAssetOrchestrator()
    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir(parents=True)
    
    plan = {
        "beats": [
            {
                "id": "vb-01",
                "beat_id": "vb-01",
                "render_strategy": "authentic_capture",
                "evidence_class": "approved_source_visual",
                "fallback_policy": "block",
                "asset_id": "cap_proof_01",
                "visual_intent": "Official benchmark screenshot",
            }
        ]
    }
    topic = {"topic_family": "agent_evaluation", "title": "Benchmark Proof"}
    
    # Enable AI visual in env
    os.environ["AI_VISUAL_ENABLED"] = "1"
    try:
        res = orchestrator.orchestrate_plan_assets(proj_dir, plan, topic)
        beat_res = res["beat_results"]["vb-01"]
        # Must block with STATUS_BLOCKED_MISSING_PROOF, NOT generate AI illustration
        assert beat_res["status"] == VisualAssetOrchestrator.STATUS_BLOCKED_MISSING_PROOF
        assert not (proj_dir / "assets" / "visuals" / "cap_proof_01.png").is_file()
    finally:
        os.environ.pop("AI_VISUAL_ENABLED", None)


def test_meaningful_svg_fallback(tmp_path: Path):
    """T10: Conceptual beat with AI visual disabled falls back to contextual SVG."""
    orchestrator = VisualAssetOrchestrator()
    proj_dir = tmp_path / "test_proj_svg"
    proj_dir.mkdir(parents=True)
    
    plan = {
        "beats": [
            {
                "id": "vb-01",
                "beat_id": "vb-01",
                "render_strategy": "ai_illustration_eligible",
                "evidence_class": "illustration",
                "fallback_policy": "typographic_card",
                "asset_id": "art_conceptual_01",
                "visual_intent": "Developer debugging agent session memory",
            }
        ]
    }
    topic = {"topic_family": "context_memory", "title": "Memory Boundary"}
    
    # Disable AI visual
    os.environ["AI_VISUAL_ENABLED"] = "0"
    res = orchestrator.orchestrate_plan_assets(proj_dir, plan, topic)
    beat_res = res["beat_results"]["vb-01"]
    
    assert beat_res["status"] == VisualAssetOrchestrator.STATUS_FALLBACK_CONTEXTUAL
    svg_file = Path(beat_res["file"])
    assert svg_file.is_file()
    assert svg_file.suffix == ".svg"
    svg_content = svg_file.read_text()
    assert "<svg" in svg_content


def test_missing_dom_binding_fails(tmp_path: Path):
    """T07: Authentic capture asset exists in visuals/ but is omitted from HTML DOM -> QA fails."""
    proj = tmp_path / "proj_missing_dom"
    proj.mkdir(parents=True)
    art = proj / "artifacts"
    art.mkdir()
    vis = proj / "assets" / "visuals"
    vis.mkdir(parents=True)
    
    # Create staged capture asset
    (vis / "cap_test_01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 600)
    
    # Visual plan specifies authentic_capture using this asset
    plan = {
        "schema_version": "1.0",
        "total_duration_seconds": 68.0,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "render_strategy": "authentic_capture",
                "visual_kind": "authentic_photo",
                "evidence_class": "approved_source_visual",
                "asset_ids": ["cap_test_01"],
            }
        ]
    }
    (art / "news_visual_plan.json").write_text(json.dumps(plan))
    
    # HTML DOM completely omits the asset cap_test_01!
    html_dir = proj / "hyperframes"
    html_dir.mkdir()
    (html_dir / "index.html").write_text("<html><body><div id='scene-1'>Hello World without image</div></body></html>")
    
    qa_res = run_news_visual_qa(proj, mode="strict")
    assert not qa_res["passed"], "Expected strict QA to fail when proof asset is omitted from HTML DOM"
    assert "VISUAL_NOT_RENDERED" in qa_res.get("failure_categories", [])


def test_claim_visual_mismatch_fails(tmp_path: Path):
    """T08: Script section discusses tool permissions, but HTML visual has unrelated text and no matching asset."""
    proj = tmp_path / "proj_mismatch"
    proj.mkdir(parents=True)
    art = proj / "artifacts"
    art.mkdir()
    vis = proj / "assets" / "visuals"
    vis.mkdir(parents=True)
    
    (art / "script_en_US.json").write_text(json.dumps({
        "sections": [
            {
                "id": "sec_0",
                "text": "Model Context Protocol enforces strict sandbox tool permissions and socket boundaries.",
            }
        ]
    }))
    
    plan = {
        "schema_version": "1.0",
        "total_duration_seconds": 68.0,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "render_strategy": "deterministic_svg",
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "asset_ids": ["diag_permissions_01"],
            }
        ]
    }
    (art / "news_visual_plan.json").write_text(json.dumps(plan))
    
    # HTML contains completely unrelated text and no diag_permissions_01 asset reference!
    html_dir = proj / "hyperframes"
    html_dir.mkdir()
    (html_dir / "index.html").write_text("<html><body><div id='scene-vb-01'>Top crypto trading meme coins</div></body></html>")
    
    qa_res = run_news_visual_qa(proj, mode="strict")
    assert not qa_res["passed"], "Expected strict QA to fail on semantic claim/visual mismatch"
    assert "CLAIM_VISUAL_MISMATCH" in qa_res.get("failure_categories", [])
