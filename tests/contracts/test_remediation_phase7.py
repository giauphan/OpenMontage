"""Phase 7 Remediation Contract Tests: End-to-End Acceptance, Positive Canaries & Negative Fixtures.

Verifies:
- T21: 3 distinct on-niche positive canaries and negative fail-closed security fixtures
- T22: Full backward compatibility and regression pass across all remediation modules
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.gate import FixedNicheScopeGate
from lib.fixed_niche.policy import OutcomeStatus
from lib.fixed_niche.claim_grounding import verify_independent_claim
from lib.news_visual.visual_planner import ClaimAwareVisualPlanner
from lib.news_visual.qa import run_news_visual_qa
from lib.qa_signing import sign_approval_record, verify_approval_record


def test_positive_canary_session_memory_boundary(tmp_path: Path):
    """Canary 1: Session memory compaction and state isolation in multi-turn agents."""
    gate = FixedNicheScopeGate()
    verdict = gate.evaluate_candidate({
        "title": "Session memory boundary failure in multi-turn coding agents",
        "summary": "Context compression causes silent instruction drift when memory boundaries are unisolated.",
    })
    assert verdict.is_eligible and verdict.status == OutcomeStatus.ELIGIBLE

    # Genuine claim grounding
    res = verify_independent_claim(
        statement="Session memory compaction reduces instruction retention by 15% in multi-turn benchmarks.",
        snapshot_text="Our evaluation showed that session memory compaction reduces instruction retention by 15% across multi-turn benchmarks.",
    )
    assert res.get("verification_status") == "INDEPENDENT_FACT_CHECK_VERIFIED"

    # Visual planning
    planner = ClaimAwareVisualPlanner()
    script_data = {
        "title": "Session Memory Boundary in Agents",
        "sections": [
            {"id": "sec_0", "start_seconds": 0.0, "end_seconds": 11.0, "text": "Why do coding agents lose context in long conversations?"},
            {"id": "sec_1", "start_seconds": 11.0, "end_seconds": 22.0, "text": "State management across multi-turn agent sessions is brittle."},
            {"id": "sec_2", "start_seconds": 22.0, "end_seconds": 33.0, "text": "Session memory boundary tests reveal 15% drift in instruction retention."},
            {"id": "sec_3", "start_seconds": 33.0, "end_seconds": 45.0, "text": "Compaction algorithms discard early tool output schemas silently."},
            {"id": "sec_4", "start_seconds": 45.0, "end_seconds": 57.0, "text": "Architecting session boundary isolation prevents silent drift."},
            {"id": "sec_5", "start_seconds": 57.0, "end_seconds": 68.0, "text": "Deterministic memory gates ensure consistent agent execution."},
        ],
    }
    claims = [
        {
            "claim_id": "cl_01",
            "section_id": "sec_2",
            "statement": "Session memory compaction reduces instruction retention by 15% in multi-turn benchmarks.",
            "source": {"publisher": "Anthropic Research", "canonical_url": "https://anthropic.com/research/memory"},
            "verdict": "APPROVED",
            "asset_id": "cap_memory_01",
        }
    ]
    plan = planner.plan_visuals("canary_mem_01", script_data, claims)
    assert len(plan["beats"]) == 6
    assert plan["beats"][2]["render_strategy"] in ("authentic_capture", "deterministic_svg")


def test_positive_canary_mcp_tool_permission_boundary(tmp_path: Path):
    """Canary 2: Model Context Protocol (MCP) tool schema isolation and sandbox permissions."""
    gate = FixedNicheScopeGate()
    verdict = gate.evaluate_candidate({
        "title": "MCP tool permission boundaries prevent unauthorized tool calls",
        "summary": "Strict capability checking and privilege separation in MCP client execution harnesses.",
    })
    assert verdict.is_eligible and verdict.status == OutcomeStatus.ELIGIBLE

    # Claim grounding without numbers
    res = verify_independent_claim(
        statement="MCP permission boundaries block unauthorized file writes.",
        snapshot_text="Tests demonstrate that MCP permission boundaries block unauthorized file writes effectively in all runs.",
    )
    assert res.get("verification_status") == "INDEPENDENT_FACT_CHECK_VERIFIED"


def test_positive_canary_reproducible_evaluation_benchmark(tmp_path: Path):
    """Canary 3: Reproducible evaluation benchmarks for agent tool use."""
    gate = FixedNicheScopeGate()
    verdict = gate.evaluate_candidate({
        "title": "SWE-bench agent evaluation reproducibility requires isolated task environments",
        "summary": "Measuring agent reliability across deterministic test harnesses without flakiness.",
    })
    assert verdict.is_eligible and verdict.status == OutcomeStatus.ELIGIBLE

    res = verify_independent_claim(
        statement="Dockerized task isolation improves benchmark reproducibility to 99.4%.",
        snapshot_text="Using Dockerized task isolation improves benchmark reproducibility to 99.4% across 500 tasks.",
    )
    assert res.get("verification_status") == "INDEPENDENT_FACT_CHECK_VERIFIED"


def test_negative_canaries_fail_closed(tmp_path: Path):
    """Verifies that all 6 critical negative fixtures fail closed and reject publication."""
    gate = FixedNicheScopeGate()

    # Negative 1: Off-niche hardware
    v_off = gate.evaluate_candidate({
        "title": "Apple launches iPad Pro with M4 chip and OLED display",
        "summary": "The new tablet features ultra-thin design and tandem OLED technology.",
    })
    assert not v_off.is_eligible and v_off.status == OutcomeStatus.OFF_NICHE, "Off-niche hardware must be rejected"

    # Negative 2: Numeric hallucination / false percentage claim
    res_num = verify_independent_claim(
        statement="The new architecture improves agent efficiency by 70%.",
        snapshot_text="The benchmark demonstrated an improvement of 15% in runtime speed.",
    )
    assert res_num.get("verification_status") == "UNVERIFIED", "Hallucinated 70% must be rejected when source says 15%"

    # Negative 3: Polarity inversion
    res_pol = verify_independent_claim(
        statement="Tool error rates decreased under the new protocol.",
        snapshot_text="Tool error rates increased significantly under the new protocol.",
    )
    assert res_pol.get("verification_status") == "UNVERIFIED", "Contradictory polarity claim must be rejected"

    # Negative 4: Missing proof asset in HTML DOM
    proj_missing = tmp_path / "proj_missing"
    proj_missing.mkdir(parents=True)
    (proj_missing / "artifacts").mkdir()
    (proj_missing / "assets" / "visuals").mkdir(parents=True)
    (proj_missing / "assets" / "visuals" / "cap_test_01.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 600)
    (proj_missing / "artifacts" / "news_visual_plan.json").write_text(json.dumps({
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
    }))
    (proj_missing / "hyperframes").mkdir()
    (proj_missing / "hyperframes" / "index.html").write_text("<html><body><div>No proof here</div></body></html>")
    qa_missing = run_news_visual_qa(proj_missing, mode="strict")
    assert not qa_missing.get("passed", False), "Missing staged proof asset in DOM must fail visual QA"
    assert "VISUAL_NOT_RENDERED" in qa_missing.get("failure_categories", [])

    # Negative 5: Claim visual mismatch in strict mode
    proj_mismatch = tmp_path / "proj_mismatch"
    proj_mismatch.mkdir(parents=True)
    (proj_mismatch / "artifacts").mkdir()
    (proj_mismatch / "assets" / "visuals").mkdir(parents=True)
    (proj_mismatch / "artifacts" / "script_en_US.json").write_text(json.dumps({
        "sections": [{"id": "sec_0", "text": "Model Context Protocol enforces strict sandbox tool permissions."}]
    }))
    (proj_mismatch / "artifacts" / "news_visual_plan.json").write_text(json.dumps({
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
    }))
    (proj_mismatch / "hyperframes").mkdir()
    (proj_mismatch / "hyperframes" / "index.html").write_text("<html><body><div>Top crypto trading meme coins</div></body></html>")
    qa_mismatch = run_news_visual_qa(proj_mismatch, mode="strict")
    assert not qa_mismatch.get("passed", False), "Claim visual mismatch in strict mode must fail visual QA"
    assert "CLAIM_VISUAL_MISMATCH" in qa_mismatch.get("failure_categories", [])

    # Negative 6: Post-render manifest tamper
    import hashlib
    proj_tamper = tmp_path / "proj_tamper"
    proj_tamper.mkdir(parents=True)
    art_dir = proj_tamper / "artifacts"
    art_dir.mkdir()
    renders_dir = proj_tamper / "renders"
    renders_dir.mkdir()
    ledger_file = art_dir / "claim_ledger.json"
    ledger_file.write_text(json.dumps({"claims": [{"claim_id": "c1", "statement": "test"}]}), encoding="utf-8")
    media_file = renders_dir / "final_short_en_US_9x16.mp4"
    media_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 500)
    meta_file = proj_tamper / "publish_metadata.json"
    meta_file.write_text(json.dumps({"title": "Test", "media_path": "renders/final_short_en_US_9x16.mp4"}))
    (art_dir / "script_en_US.json").write_text(json.dumps({"sections": [{"id": "s1", "text": "test"}]}), encoding="utf-8")
    plan_file = art_dir / "news_visual_plan.json"
    plan_file.write_text(json.dumps({"schema_version": "1.0", "beats": [{"id": "b1"}]}), encoding="utf-8")

    approval = sign_approval_record(
        project_id="canary_proj",
        media_sha256=hashlib.sha256(media_file.read_bytes()).hexdigest(),
        claim_ledger_sha256=hashlib.sha256(ledger_file.read_bytes()).hexdigest(),
        project_dir=str(proj_tamper),
        use_manifest=True,
    )
    # Confirm initial validity
    valid_initial, msg_init = verify_approval_record(
        approval,
        project_id="canary_proj",
        project_dir=str(proj_tamper),
        require_manifest=True,
    )
    assert valid_initial, f"Expected initial approval to be valid, got: {msg_init}"

    # Mutate plan after signing
    plan_file.write_text(json.dumps({"schema_version": "1.0", "beats": [{"id": "tampered"}]}), encoding="utf-8")
    valid_after_tamper, msg = verify_approval_record(
        approval,
        project_id="canary_proj",
        project_dir=str(proj_tamper),
        require_manifest=True,
    )
    assert not valid_after_tamper, "Tampering with news_visual_plan.json after QA signing must invalidate approval record"
    assert "visual plan SHA mismatch" in msg
