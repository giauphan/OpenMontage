"""Contract tests for AnimatedDiagramDirector and DiagramAnimationPlan.

Covers AC-008, AC-011, AC-012.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.visual_style.diagram_director import AnimatedDiagramDirector
from lib.visual_style.validation import validate_diagram_plan_data
from lib.visual_style.qa import evaluate_plan_qa


@pytest.mark.parametrize("family,title,viewer_q", [
    (
        "context_memory",
        "Why coding agents forget project instructions between sessions",
        "Why does a coding agent lose context rules when you start a new session?",
    ),
    (
        "agent_tool_use",
        "What actually happens when an AI agent calls an MCP tool",
        "What happens under the hood when a coding agent invokes a tool via MCP?",
    ),
    (
        "debugging_reliability",
        "Why an agent patch passes one test but fails the full project",
        "Why can an AI agent's patch pass a single targeted test but break the whole suite?",
    ),
])
def test_director_generates_valid_contract_for_topic_families(tmp_path: Path, family: str, title: str, viewer_q: str):
    """Director creates schema-compliant, referentially valid DiagramAnimationPlan for each family."""
    director = AnimatedDiagramDirector(policy_sha256="a" * 64)
    topic = {
        "candidate_id": f"test_{family}",
        "title": title,
        "topic_family": family,
        "viewer_question": viewer_q,
    }
    claims = [
        {"claim_id": "C001", "statement": f"Primary claim for {family}"},
        {"claim_id": "C002", "statement": f"Secondary claim for {family}"},
        {"claim_id": "C003", "statement": f"Verification claim for {family}"},
    ]

    plan = director.plan_diagram_animation(
        project_id=f"proj_{family}",
        topic=topic,
        claims=claims,
        target_duration=72.0,
        script_sha256="1" * 64,
        source_claim_ledger_sha256="2" * 64,
        source_visual_plan_sha256="3" * 64,
    )

    plan_dict = plan.to_dict()
    errors = validate_diagram_plan_data(plan_dict, strict_hashes=True)
    assert not errors, f"Plan for {family} has validation errors: {errors}"

    qa_report = evaluate_plan_qa(plan, strict_hashes=True)
    assert qa_report["status"] == "PASS", f"QA evaluation failed for {family}: {qa_report}"
    assert 65.0 <= plan.duration_seconds <= 75.0
    assert 6 <= len(plan.beats) <= 12
    for b in plan.beats:
        hold = b.end_seconds - b.start_seconds
        assert 0 < hold <= 12.0

    # Write sidecar and verify on-disk JSON
    sidecar_path = director.write_sidecar(plan, tmp_path)
    assert sidecar_path.is_file()
    loaded_dict = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert loaded_dict["project_id"] == f"proj_{family}"
    assert loaded_dict["style"] == "animated_agent_diagram_v1"
