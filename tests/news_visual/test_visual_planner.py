"""Unit tests for lib.news_visual.visual_planner.

Verifies:
1. Missing claim fails closed.
2. Rejected claim fails closed.
3. Empty sources fail closed.
4. Off-niche topic fails closed.
5. Contradictory claim fails closed.
6. Total timeline < 65s or > 75s fails closed.
7. Beat duration > 12s fails closed.
8. Valid plan generation produces 6-8 beats with proof vs conceptual separation.
9. Retiming plan preserves visual intent and asset IDs without resetting.
"""
from __future__ import annotations

import pytest
from lib.news_visual.visual_planner import ClaimAwareVisualPlanner, VisualPlannerError


@pytest.fixture
def valid_claims():
    return [
        {
            "claim_id": "C001",
            "statement": "Large language models maintain zero persistent state across independent sessions.",
            "verdict": "APPROVED",
            "confidence": "verified",
            "source": {
                "canonical_url": "https://docs.anthropic.com/context",
                "publisher": "Anthropic Docs",
            },
        },
        {
            "claim_id": "C002",
            "statement": "Declarative AGENTS contracts at repo root provide persistent session rules.",
            "verdict": "APPROVED",
            "confidence": "verified",
            "source": {
                "canonical_url": "https://modelcontextprotocol.io/spec",
                "publisher": "MCP Spec",
            },
        },
    ]


@pytest.fixture
def valid_script():
    # 6 sections totaling 70s, each between 10-12s
    return {
        "version": "1.0",
        "title": "Why Agents Forget Rules",
        "sections": [
            {"id": "sec_0", "narration": "Why does your AI coding agent forget rules between sessions?", "start_seconds": 0.0, "end_seconds": 11.0},
            {"id": "sec_1", "narration": "You provide detailed instructions, but the next session resets to zero.", "start_seconds": 11.0, "end_seconds": 22.0},
            {"id": "sec_2", "narration": "The architectural cause is ephemeral process context in LLM runners.", "start_seconds": 22.0, "end_seconds": 34.0},
            {"id": "sec_3", "narration": "The engineering remedy is declarative configuration persisted on disk.", "start_seconds": 34.0, "end_seconds": 46.0},
            {"id": "sec_4", "narration": "Verify this locally with isolated test runs before committing changes.", "start_seconds": 46.0, "end_seconds": 58.0},
            {"id": "sec_5", "narration": "Enforce persistent boundary contracts in CI rather than conversational memory.", "start_seconds": 58.0, "end_seconds": 70.0},
        ],
    }


def test_planner_rejects_empty_claims(valid_script):
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="claim_ledger cannot be empty"):
        planner.plan_visuals("proj_1", valid_script, [])


def test_planner_rejects_rejected_claims(valid_script, valid_claims):
    valid_claims[0]["verdict"] = "REJECTED"
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="has REJECTED verdict"):
        planner.plan_visuals("proj_1", valid_script, valid_claims)


def test_planner_rejects_missing_source(valid_script, valid_claims):
    valid_claims[0]["source"] = {}
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="lacks authentic source"):
        planner.plan_visuals("proj_1", valid_script, valid_claims)


def test_planner_rejects_contradictory_claims(valid_script, valid_claims):
    valid_claims.append({
        "claim_id": "C003",
        "statement": "not large language models maintain zero persistent state across independent sessions.",
        "verdict": "APPROVED",
        "confidence": "verified",
        "source": {"canonical_url": "https://example.com", "publisher": "Test"},
    })
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="Contradictory claim detected"):
        planner.plan_visuals("proj_1", valid_script, valid_claims)


def test_planner_rejects_off_niche_topic(valid_script, valid_claims):
    planner = ClaimAwareVisualPlanner()
    off_niche_topic = {
        "title": "Celebrity tech billionaire luxury yacht tour",
        "body": "Parties and gossip in Hollywood.",
    }
    with pytest.raises(VisualPlannerError, match="FixedNicheScopeGate"):
        planner.plan_visuals("proj_1", valid_script, valid_claims, topic=off_niche_topic)


def test_planner_rejects_short_total_duration(valid_script, valid_claims):
    # Total duration = 48s (< 65s), each section 8s
    for idx, sec in enumerate(valid_script["sections"]):
        sec["start_seconds"] = idx * 8.0
        sec["end_seconds"] = (idx + 1) * 8.0
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="outside required window"):
        planner.plan_visuals("proj_1", valid_script, valid_claims)


def test_planner_rejects_beat_exceeding_12s(valid_script, valid_claims):
    # Beat 1 duration = 14s (> 12s)
    valid_script["sections"][0]["end_seconds"] = 14.0
    planner = ClaimAwareVisualPlanner()
    with pytest.raises(VisualPlannerError, match="exceeds maximum 12.0s"):
        planner.plan_visuals("proj_1", valid_script, valid_claims)


def test_planner_success_6_beats(valid_script, valid_claims):
    planner = ClaimAwareVisualPlanner()
    in_niche_topic = {
        "title": "Why coding agents lose memory between sessions",
        "topic_family": "context_memory",
    }
    plan = planner.plan_visuals("proj_test", valid_script, valid_claims, topic=in_niche_topic)
    assert plan["version"] == "1.0"
    assert plan["enabled"] is True
    assert len(plan["beats"]) == 6

    # Verify AI art eligibility: 2 to 4 beats eligible for AI art
    ai_beats = [b for b in plan["beats"] if b["render_strategy"] == "ai_illustration_eligible"]
    assert 2 <= len(ai_beats) <= 4

    # Verify proof beats have deterministic_svg or authentic_capture
    proof_beats = [b for b in plan["beats"] if b["render_strategy"] in ("deterministic_svg", "authentic_capture")]
    assert len(proof_beats) >= 2

    # Verify all beats have non-empty visual_intent
    for beat in plan["beats"]:
        assert beat["visual_intent"]
        assert len(beat["visual_intent"]) > 10
        assert beat["end_seconds"] - beat["start_seconds"] <= 12.0


def test_retime_plan_preserves_intent_and_assets(valid_script, valid_claims):
    planner = ClaimAwareVisualPlanner()
    original_plan = planner.plan_visuals("proj_test", valid_script, valid_claims)
    orig_intent_0 = original_plan["beats"][0]["visual_intent"]
    orig_asset_0 = original_plan["beats"][0]["asset_ids"]

    # Retimed script (audio timing shifted slightly, but still within [65, 75] and <=12s per beat)
    retimed_script = {
        "version": "1.0",
        "title": "Why Agents Forget Rules",
        "sections": [
            {"id": "sec_0", "narration": "Why does your AI coding agent forget rules between sessions?", "start_seconds": 0.0, "end_seconds": 10.5},
            {"id": "sec_1", "narration": "You provide detailed instructions, but the next session resets to zero.", "start_seconds": 10.5, "end_seconds": 21.0},
            {"id": "sec_2", "narration": "The architectural cause is ephemeral process context in LLM runners.", "start_seconds": 21.0, "end_seconds": 32.5},
            {"id": "sec_3", "narration": "The engineering remedy is declarative configuration persisted on disk.", "start_seconds": 32.5, "end_seconds": 44.0},
            {"id": "sec_4", "narration": "Verify this locally with isolated test runs before committing changes.", "start_seconds": 44.0, "end_seconds": 55.5},
            {"id": "sec_5", "narration": "Enforce persistent boundary contracts in CI rather than conversational memory.", "start_seconds": 55.5, "end_seconds": 67.0},
        ],
    }

    retimed_plan = planner.retime_plan(original_plan, retimed_script)
    assert retimed_plan["beats"][0]["start_seconds"] == 0.0
    assert retimed_plan["beats"][0]["end_seconds"] == 10.5
    # Preserves exact visual intent and asset ID
    assert retimed_plan["beats"][0]["visual_intent"] == orig_intent_0
    assert retimed_plan["beats"][0]["asset_ids"] == orig_asset_0
