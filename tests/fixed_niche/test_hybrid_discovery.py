"""Tests for Option C: Hybrid Tiered Strategy (HybridCandidateDiscovery)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.hybrid_discovery import (
    HybridCandidateDiscovery,
    DiscoveryTier,
    TieredDiscoveryResult,
)
from lib.fixed_niche.policy import OutcomeStatus


@pytest.fixture
def discovery_env(tmp_path: Path):
    """Sets up an isolated discovery environment with mock data directory."""
    root = tmp_path / "app"
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    curated_file = data_dir / "daily_candidates.json"
    feed_file = data_dir / "newsnow_feed.json"

    # Default valid in-scope candidates
    curated_candidates = [
        {
            "candidate_id": "cand_curated_01",
            "title": "How AI Coding Agents Handle Tool Calling and Permission Boundaries",
            "topic_family": "agent_tool_use",
            "canonical_url": "https://docs.anthropic.com/claude/tool-use",
            "summary": "Analyzing MCP tool schemas and sandbox permission boundaries.",
        },
        {
            "candidate_id": "cand_curated_02",
            "title": "Why coding agents lose project requirements between sessions",
            "topic_family": "context_memory",
            "canonical_url": "https://docs.anthropic.com/claude/context-window",
            "summary": "Context window limits require durable disk file persistence.",
        },
    ]
    curated_file.write_text(json.dumps(curated_candidates, indent=2), encoding="utf-8")

    feed_candidates = [
        {
            "candidate_id": "cand_feed_01",
            "title": "Debugging Flaky Tools and Retry Storms in Autonomous Agent Workflows",
            "topic_family": "debugging_reliability",
            "canonical_url": "https://github.com/swe-bench/eval",
            "summary": "Investigating unhandled tool exceptions and test-driven repair loops.",
        }
    ]
    feed_file.write_text(json.dumps(feed_candidates, indent=2), encoding="utf-8")

    return {
        "root": root,
        "curated_file": curated_file,
        "feed_file": feed_file,
    }


def test_tier_1_curated_queue_priority(discovery_env):
    """Tier 1 curated backlog must be prioritized over Tier 2 automated feed."""
    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    assert res.tier == DiscoveryTier.TIER_1_CURATED
    assert len(res.candidates) == 1
    assert res.candidates[0]["candidate_id"] == "cand_curated_01"
    assert res.candidates[0]["topic_family"] == "agent_tool_use"


def test_consumed_candidate_advancement(discovery_env):
    """When the first candidate is consumed, the queue automatically advances to the second."""
    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    # 1. First run selects cand_curated_01
    res1 = discovery.discover_candidates(count=1)
    assert res1.candidates[0]["candidate_id"] == "cand_curated_01"

    # 2. Mark first candidate as consumed
    discovery.mark_candidate_consumed("cand_curated_01")
    assert "cand_curated_01" in discovery.get_used_project_ids()

    # 3. Second run advances to cand_curated_02
    res2 = discovery.discover_candidates(count=1)
    assert res2.is_eligible is True
    assert res2.tier == DiscoveryTier.TIER_1_CURATED
    assert res2.candidates[0]["candidate_id"] == "cand_curated_02"


def test_tier_2_automated_feed_fallback_when_curated_exhausted(discovery_env):
    """When all curated candidates are consumed, discovery seamlessly falls back to Tier 2 feed."""
    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    # Consume both curated candidates
    discovery.mark_candidate_consumed("cand_curated_01")
    discovery.mark_candidate_consumed("cand_curated_02")

    # Discover should now fall back to feed
    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    assert res.tier == DiscoveryTier.TIER_2_AUTOMATED
    assert len(res.candidates) == 1
    assert res.candidates[0]["candidate_id"] == "cand_feed_01"
    assert res.candidates[0]["topic_family"] == "debugging_reliability"


def test_missing_curated_file_falls_back_to_tier_2(discovery_env):
    """If curated backlog file is missing entirely, Tier 2 feed is used without error."""
    missing_curated = discovery_env["root"] / "non_existent.json"
    discovery = HybridCandidateDiscovery(
        curated_path=missing_curated,
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    assert res.tier == DiscoveryTier.TIER_2_AUTOMATED
    assert res.candidates[0]["candidate_id"] == "cand_feed_01"


def test_niche_gate_filters_off_niche_candidates(discovery_env):
    """Candidates in curated or feed files that violate locked niche must be rejected."""
    bad_curated = [
        {
            "candidate_id": "cand_bad_hype",
            "title": "Top 10 AI dating apps and celebrity crypto trading",
            "canonical_url": "https://example.com/hype",
            "summary": "Viral make money online listicle.",
        }
    ]
    discovery_env["curated_file"].write_text(json.dumps(bad_curated), encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    # Bad curated item rejected by gate; cascades to valid Tier 2 candidate
    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    assert res.tier == DiscoveryTier.TIER_2_AUTOMATED
    assert res.candidates[0]["candidate_id"] == "cand_feed_01"


def test_fail_closed_when_both_tiers_empty_or_off_niche(discovery_env):
    """When neither tier provides eligible topics, clean NO_ELIGIBLE_TOPIC is returned."""
    empty_file = discovery_env["root"] / "empty.json"
    empty_file.write_text("[]", encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=empty_file,
        feed_path=empty_file,
        root_dir=discovery_env["root"],
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is False
    assert res.tier == DiscoveryTier.NONE
    assert res.status == OutcomeStatus.NO_ELIGIBLE_TOPIC.value
    assert "Zero in-scope candidates" in res.reason


def test_existing_rendered_project_is_deduplicated(discovery_env):
    """If candidate ID already exists in projects/ with an MP4 render, it is deduplicated."""
    p_dir = discovery_env["root"] / "projects" / "cand_curated_01" / "renders"
    p_dir.mkdir(parents=True, exist_ok=True)
    (p_dir / "final_short_en_US_9x16.mp4").write_text("fake_video_bytes")

    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )

    # cand_curated_01 has an existing render on disk; should automatically skip to cand_curated_02
    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    assert res.candidates[0]["candidate_id"] == "cand_curated_02"
