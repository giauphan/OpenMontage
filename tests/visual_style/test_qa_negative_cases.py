"""Negative test cases and fault injection for Diagram QA.

Covers AC-007, AC-008, AC-009, AC-015, AC-025.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from lib.visual_style.diagram_director import AnimatedDiagramDirector
from lib.visual_style.qa import evaluate_plan_qa
from lib.visual_style.spec import DiagramAnimationPlan
from lib.visual_style.validation import validate_diagram_plan_data


@pytest.fixture
def valid_plan() -> DiagramAnimationPlan:
    director = AnimatedDiagramDirector()
    topic = {
        "candidate_id": "test_qa_neg",
        "title": "Why coding agents forget context",
        "topic_family": "context_memory",
    }
    claims = [{"claim_id": "C001", "statement": "Test claim"}]
    return director.plan_diagram_animation("test_neg", topic, claims, target_duration=72.0)


def test_reject_duplicate_node_ids(valid_plan: DiagramAnimationPlan):
    """Duplicate node IDs must fail contract validation."""
    data = valid_plan.to_dict()
    # Duplicate first node
    dup_node = deepcopy(data["graph"]["nodes"][0])
    data["graph"]["nodes"].append(dup_node)
    errors = validate_diagram_plan_data(data)
    assert any("duplicate IDs" in err for err in errors)


def test_reject_nonexistent_event_target(valid_plan: DiagramAnimationPlan):
    """Event targeting a nonexistent node or edge must fail contract validation."""
    data = valid_plan.to_dict()
    data["events"][0]["target"] = "nonexistent_target_id"
    errors = validate_diagram_plan_data(data)
    assert any("not found in nodes or edges" in err for err in errors)


def test_reject_event_outside_beat_window(valid_plan: DiagramAnimationPlan):
    """Event timestamp outside its corresponding beat's range must fail contract validation."""
    data = valid_plan.to_dict()
    # Move event 0 to 50s while its beat ends at 9s
    data["events"][0]["at_seconds"] = 50.0
    errors = validate_diagram_plan_data(data)
    assert any("outside beat" in err for err in errors)


def test_qa_rejects_plan_with_empty_beat(valid_plan: DiagramAnimationPlan):
    """A beat with zero events (static slide) must fail semantic QA."""
    # Remove all events belonging to beat 1
    valid_plan.events = [e for e in valid_plan.events if e.beat_id != valid_plan.beats[0].id]
    qa_report = evaluate_plan_qa(valid_plan)
    assert qa_report["status"] == "FAIL"
    assert valid_plan.beats[0].id in qa_report["empty_beats"]


def test_qa_rejects_beat_exceeding_12s(valid_plan: DiagramAnimationPlan):
    """A beat with hold > 12.0s must fail QA hold check."""
    # Mutate beat 0 to have 15s hold
    b0 = valid_plan.beats[0]
    from lib.visual_style.spec import TimedVisualBeat
    valid_plan.beats[0] = TimedVisualBeat(
        id=b0.id,
        section_id=b0.section_id,
        start_seconds=0.0,
        end_seconds=15.0,  # 15s hold!
        claim_ids=b0.claim_ids,
        visual_intent=b0.visual_intent,
    )
    qa_report = evaluate_plan_qa(valid_plan)
    assert qa_report["status"] == "FAIL"
    assert len(qa_report["violating_hold_beats"]) > 0


def test_qa_rejects_placeholder_hashes_in_strict_mode(valid_plan: DiagramAnimationPlan):
    """Strict QA mode must reject all-zero placeholder hashes."""
    qa_report = evaluate_plan_qa(valid_plan, strict_hashes=True)
    assert qa_report["status"] == "FAIL"
    assert any("placeholder/invalid hash" in err for err in qa_report["schema_errors"])
