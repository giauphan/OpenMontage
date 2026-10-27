"""Tests for production-reachable niche scope gating.

Covers AC-001.
"""
from __future__ import annotations

import pytest

from lib.fixed_niche.gate import FixedNicheScopeGate
from lib.fixed_niche.policy import OutcomeStatus


def test_niche_gate_rejects_off_niche_candidates():
    """Daily intake must reject candidates from blocked topic domains."""
    gate = FixedNicheScopeGate()
    off_niche_list = [
        {"candidate_id": "c_art", "title": "Runway Gen-3 and Kling 1.5 Video Generation Shootout"},
        {"candidate_id": "c_crypto", "title": "Make $10k Monthly With Solana Meme Coin Arbitrage"},
        {"candidate_id": "c_hw", "title": "Nvidia RTX 5090 Benchmark Review and Battery Comparison"},
        {"candidate_id": "c_pol", "title": "Senate Committee Passes Federal AI Regulatory Bill"},
        {"candidate_id": "c_gossip", "title": "Tech Billionaire Hosts Lavish Hollywood Yacht Party"},
    ]
    for c in off_niche_list:
        verdict = gate.evaluate_candidate(c)
        assert verdict.is_eligible is False, f"Candidate {c['title']} was erroneously accepted"
        assert verdict.status == OutcomeStatus.OFF_NICHE
        assert verdict.topic_family is None


def test_niche_gate_accepts_valid_engineering_topics():
    """Daily intake accepts topics within the 5 authorized agent engineering families."""
    gate = FixedNicheScopeGate()
    valid_list = [
        ("context_memory", {"candidate_id": "c_mem", "title": "Why coding agents lose project requirements between sessions", "body": "Context windows reset while durable repo instructions persist.", "topic_family": "context_memory"}),
        ("agent_tool_use", {"candidate_id": "c_tool", "title": "How MCP server contracts secure agent tool execution", "body": "Tool calling permissions, model context protocol schemas, and sandbox isolation.", "topic_family": "agent_tool_use"}),
        ("debugging_reliability", {"candidate_id": "c_debug", "title": "Why coding agents generate hallucinated patch retries", "body": "Failing test analysis, regression validation loops, and multi-turn debug.", "topic_family": "debugging_reliability"}),
        ("agent_evaluation", {"candidate_id": "c_eval", "title": "Benchmarking autonomous coding agents on reproducible test suites", "body": "SWE-bench evaluation, reliable metrics, and operational cost estimation.", "topic_family": "agent_evaluation"}),
        ("agent_architecture", {"candidate_id": "c_arch", "title": "Multi-agent orchestration vs single-agent checkpoints", "body": "Handoff protocols, durable state checkpoints, and supervisory coordination.", "topic_family": "agent_architecture"}),
    ]
    for expected_family, c in valid_list:
        verdict = gate.evaluate_candidate(c)
        assert verdict.is_eligible is True, f"Valid candidate {c['title']} rejected: {verdict.reason}"
        assert verdict.status == OutcomeStatus.ELIGIBLE
        assert verdict.topic_family == expected_family
