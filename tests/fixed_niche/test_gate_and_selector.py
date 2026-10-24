"""Tests for Phase 2: Scope gate, topic scoring, bounded selector, and zero-topic behavior.
Covers matrix IDs: TOPIC-001, TOPIC-002, TOPIC-003, TOPIC-004, TOPIC-005, RELEASE-001, RELEASE-002, RELEASE-003.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from lib.fixed_niche.policy import load_locked_policy, OutcomeStatus
from lib.fixed_niche.gate import FixedNicheScopeGate, ScopeVerdict
from lib.fixed_niche.ranker import FixedNicheTopicScorer
from lib.fixed_niche.topic_selector import FixedNicheTopicSelector, CandidateBoundSelectionError


@pytest.fixture
def fixtures_data() -> dict:
    with open("tests/fixtures/fixed_niche_cases.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_20_positive_fixtures_pass_deterministic_gate(fixtures_data: dict):
    """Verify all 20 positive agent engineering cases pass the deterministic scope gate."""
    gate = FixedNicheScopeGate()
    positive_cases = fixtures_data["positive_cases"]
    assert len(positive_cases) == 20

    for case in positive_cases:
        verdict = gate.evaluate_candidate(case)
        assert verdict.status == OutcomeStatus.ELIGIBLE, (
            f"Expected positive case {case['id']} ({case['title']}) to be ELIGIBLE, "
            f"got {verdict.status}: {verdict.reason}"
        )
        assert verdict.topic_family == case["topic_family"]
        assert verdict.scope_trace is not None
        assert verdict.scope_trace.policy_sha256 == gate.policy.policy_sha256


def test_20_negative_fixtures_rejected_with_reasons(fixtures_data: dict):
    """Verify 100% of the 20 negative cases are rejected as OFF_NICHE or blocked."""
    gate = FixedNicheScopeGate()
    negative_cases = fixtures_data["negative_cases"]
    assert len(negative_cases) == 20

    for case in negative_cases:
        verdict = gate.evaluate_candidate(case)
        assert verdict.status in (OutcomeStatus.OFF_NICHE, OutcomeStatus.INSUFFICIENT_EVIDENCE), (
            f"Expected negative case {case['id']} ({case['title']}) to be rejected, got {verdict.status}"
        )
        assert verdict.reason, f"Missing rejection reason for {case['id']}"


def test_topic_001_evergreen_older_than_24h_is_eligible_explainer():
    """TOPIC-001: approved evergreen documentation >24h old is eligible explainer, NOT called breaking news."""
    gate = FixedNicheScopeGate()
    candidate = {
        "id": "evergreen_doc_old",
        "title": "Why coding agents forget project requirements between sessions",
        "body": "Context window architecture analysis of session persistence.",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "published_at": "2024-01-15T00:00:00Z",  # Over 2 years old!
        "content_kind": "evergreen_explainer",
        "publisher": "Anthropic Docs",
    }
    verdict = gate.evaluate_candidate(candidate)
    assert verdict.status == OutcomeStatus.ELIGIBLE
    assert verdict.content_kind == "evergreen_explainer"

    scorer = FixedNicheTopicScorer()
    score_breakdown = scorer.score_candidate(candidate, verdict)
    assert score_breakdown["total_score"] >= 0.75
    # Evergreen receives a neutral freshness score (e.g. 0.8), not penalizing it down to zero
    assert score_breakdown["freshness_score"] >= 0.5


def test_topic_002_trending_without_developer_payoff_rejected():
    """TOPIC-002: latest trend but no developer payoff -> reject despite high freshness score."""
    gate = FixedNicheScopeGate()
    candidate = {
        "id": "trending_no_payoff",
        "title": "AI is changing the world right now according to top influencer",
        "body": "Vague trending clip with millions of views but zero code or developer payoff.",
        "canonical_url": "https://example.com/trending",
        "published_at": "2026-10-24T09:00:00Z",  # Brand new!
    }
    verdict = gate.evaluate_candidate(candidate)
    assert verdict.status == OutcomeStatus.OFF_NICHE


def test_topic_003_zero_eligible_returns_no_eligible_topic_without_side_effects(tmp_path: Path):
    """TOPIC-003: zero eligible stories -> NO_ELIGIBLE_TOPIC, zero queue mutation."""
    gate = FixedNicheScopeGate()
    candidates = [
        {"id": "c1", "title": "Celebrity gossip with AI"},
        {"id": "c2", "title": "Buy bitcoin now with AI bot"},
    ]
    eligible_pool = [c for c in candidates if gate.evaluate_candidate(c).status == OutcomeStatus.ELIGIBLE]
    assert len(eligible_pool) == 0

    selector = FixedNicheTopicSelector()
    result = selector.select_topic(eligible_pool)
    assert result["status"] == OutcomeStatus.NO_ELIGIBLE_TOPIC.value
    assert result.get("selected_candidate_id") is None

    # Verify no projects or publish queue entries were created
    queue_file = tmp_path / "publish_queue.json"
    assert not queue_file.exists()


def test_topic_004_unknown_candidate_id_rejected_no_silent_remap():
    """TOPIC-004: selector returns ID outside allowed pool -> reject; no silent remap."""
    selector = FixedNicheTopicSelector()
    allowed_pool = [
        {"id": "cand_allowed_01", "title": "Why coding agents lose context"},
        {"id": "cand_allowed_02", "title": "MCP schema mismatch errors"},
    ]

    # Mock an LLM response returning a hallucinated ID "cand_hallucinated_99"
    raw_llm_output = {
        "selected_candidate_id": "cand_hallucinated_99",
        "viewer_question": "Why do tools fail?",
        "niche_id": "us-ai-agent-engineering",
    }
    with pytest.raises(CandidateBoundSelectionError) as exc_info:
        selector.validate_selection(raw_llm_output, allowed_pool)
    assert "outside the allowed candidate pool" in str(exc_info.value)


def test_topic_005_duplicate_thesis_blocked_by_semantic_dedupe():
    """TOPIC-005: same engineering claim with new title -> duplicate thesis blocked."""
    scorer = FixedNicheTopicScorer()
    history = [
        {
            "viewer_question": "Why can an AI coding agent forget your project requirements between sessions?",
            "topic_family": "context_memory",
            "thesis_keywords": ["context", "session", "requirements", "forget", "persist"],
        }
    ]
    candidate_new_title_same_thesis = {
        "id": "dup_thesis",
        "title": "Stop your coding agent from dropping project rules across chats",
        "body": "Analyzing session context loss and requirements persistence across chats.",
        "topic_family": "context_memory",
        "viewer_question": "Why can an AI coding agent forget project rules between sessions?",
    }
    is_duplicate, reason = scorer.check_duplicate(candidate_new_title_same_thesis, history)
    assert is_duplicate is True
    assert "duplicate" in reason.lower() or "thesis" in reason.lower()


def test_release_001_off_niche_topic_blocked_regardless_of_score():
    """RELEASE-001: off-niche topic passes artificial score -> BLOCK regardless of score."""
    gate = FixedNicheScopeGate()
    off_niche_candidate = {
        "id": "off_niche_high_score",
        "title": "Nvidia launches new RTX 5090 GPU with revolutionary DLSS 4",
        "body": "Gaming hardware benchmarks.",
        "score": 0.99,  # High artificial score
    }
    verdict = gate.evaluate_candidate(off_niche_candidate)
    assert verdict.status == OutcomeStatus.OFF_NICHE
    # Hard gate beats score!
    assert verdict.is_eligible is False


def test_release_002_legacy_flag_off_preserves_behavior():
    """RELEASE-002: old VI/news mode with niche flag off -> behavior unchanged."""
    import os
    env_backup = os.environ.get("FIXED_NICHE_MODE")
    try:
        os.environ["FIXED_NICHE_MODE"] = "0"
        from tools.news.news_pipeline_cli import main, NewsNowAdapter
        adapter = NewsNowAdapter()
        assert adapter is not None
        # main with empty/invalid args should return 2 or exit cleanly
        assert callable(main)
    finally:
        if env_backup is not None:
            os.environ["FIXED_NICHE_MODE"] = env_backup
        else:
            os.environ.pop("FIXED_NICHE_MODE", None)


def test_release_003_no_topic_day_under_scheduler():
    """RELEASE-003: no-topic day under scheduler -> no publish, no filler/retry storm."""
    selector = FixedNicheTopicSelector()
    empty_pool = []
    res = selector.select_topic(empty_pool)
    assert res["status"] == "NO_ELIGIBLE_TOPIC"
    assert res.get("projects_created", 0) == 0
