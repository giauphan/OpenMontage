"""Tests for Option C: Hybrid Tiered Strategy (HybridCandidateDiscovery)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
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


def test_require_latest_news_active_by_default(discovery_env):
    """HybridCandidateDiscovery must activate require_latest_news=True by default."""
    discovery = HybridCandidateDiscovery(
        curated_path=discovery_env["curated_file"],
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
    )
    assert discovery.require_latest_news is True
    res = discovery.discover_candidates(count=1)
    assert res.diagnostics.get("require_latest_news_active") is True


def test_sort_by_recency_prioritizes_breaking_news_over_evergreen(discovery_env):
    """Breaking news candidates with publication dates take priority over evergreen explainers."""
    candidates = [
        {
            "candidate_id": "cand_evergreen_older",
            "title": "Why coding agents lose project requirements between sessions",
            "topic_family": "context_memory",
            "canonical_url": "https://docs.anthropic.com/claude/context-window",
            "summary": "Evergreen context persistence explainer.",
            "content_kind": "evergreen_explainer",
            "is_evergreen": True,
        },
        {
            "candidate_id": "cand_breaking_news_recent",
            "title": "SEP-2127 Finalized: MCP Server Cards Eliminate Agent Handshake Latency",
            "topic_family": "agent_tool_use",
            "canonical_url": "https://modelcontextprotocol.io/specification/sep-2127",
            "summary": "Latest breaking specification finalized in October 2026.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-15T00:00:00Z",
        },
    ]
    curated_path = discovery_env["root"] / "data" / "mixed_candidates.json"
    curated_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=curated_path,
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
        require_latest_news=True,
        reference_time=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    # Even though cand_evergreen_older was first in the JSON list, cand_breaking_news_recent must be selected
    assert res.candidates[0]["candidate_id"] == "cand_breaking_news_recent"
    assert res.candidates[0]["content_kind"] == "news"


def test_sort_by_recency_ranks_newer_news_first(discovery_env):
    """When multiple news items are present, the newer published date is selected first."""
    candidates = [
        {
            "candidate_id": "cand_news_early_oct",
            "title": "Early October AI Agent Tool Routing Specification",
            "topic_family": "agent_tool_use",
            "canonical_url": "https://example.com/spec-early",
            "summary": "Published on October 1st.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-01T12:00:00Z",
        },
        {
            "candidate_id": "cand_news_late_oct",
            "title": "Late October AI Agent Context Memory Standard",
            "topic_family": "context_memory",
            "canonical_url": "https://example.com/spec-late",
            "summary": "Published on October 25th.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-25T12:00:00Z",
        },
    ]
    curated_path = discovery_env["root"] / "data" / "dated_candidates.json"
    curated_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=curated_path,
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
        require_latest_news=True,
        max_age_days=30,
        reference_time=datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc),
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is True
    # cand_news_late_oct (Oct 25) must be chosen before cand_news_early_oct (Oct 1)
    assert res.candidates[0]["candidate_id"] == "cand_news_late_oct"


def test_sliding_window_freshness_for_november_run(discovery_env):
    """Simulates running on 01/11 (Nov 1): only topics from 01/11, 31/10, or up to 3 days prior are accepted."""
    # Simulated run on Nov 1, 2026 at 12:00 UTC
    simulated_run_date = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    candidates = [
        {
            "candidate_id": "cand_stale_oct15",
            "title": "Old Mid-October Tool Calling Explainer",
            "topic_family": "agent_tool_use",
            "canonical_url": "https://example.com/oct15",
            "summary": "Published 17 days ago.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-15T00:00:00Z",  # 17 days old -> STALE
        },
        {
            "candidate_id": "cand_yesterday_oct31",
            "title": "Yesterday MCP Circuit Breaker Standard",
            "topic_family": "agent_tool_use",
            "canonical_url": "https://example.com/oct31",
            "summary": "Published on 31/10.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-31T14:00:00Z",  # 1 day old (31/10) -> ACCEPTED
        },
        {
            "candidate_id": "cand_today_nov01",
            "title": "Today November 1st Subagent Handoff Specification",
            "topic_family": "agent_architecture",
            "canonical_url": "https://example.com/nov01",
            "summary": "Published on 01/11.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-11-01T08:00:00Z",  # Today (01/11) -> ACCEPTED
        },
    ]
    curated_path = discovery_env["root"] / "data" / "november_feed.json"
    curated_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=curated_path,
        feed_path=discovery_env["feed_file"],
        root_dir=discovery_env["root"],
        require_latest_news=True,
        max_age_days=3,  # Window: [2026-10-29, 2026-11-01]
        reference_time=simulated_run_date,
    )

    # First discovery should pick today's 01/11 topic
    res1 = discovery.discover_candidates(count=1)
    assert res1.is_eligible is True
    assert res1.candidates[0]["candidate_id"] == "cand_today_nov01"
    assert res1.candidates[0]["published_at_utc"] == "2026-11-01T08:00:00Z"

    # Consume today's topic; second run should pick yesterday's 31/10 topic
    discovery.mark_candidate_consumed("cand_today_nov01")
    res2 = discovery.discover_candidates(count=1)
    assert res2.is_eligible is True
    assert res2.candidates[0]["candidate_id"] == "cand_yesterday_oct31"
    assert res2.candidates[0]["published_at_utc"] == "2026-10-31T14:00:00Z"

    # Consume yesterday's topic; cand_stale_oct15 is > 3 days old and MUST be rejected
    discovery.mark_candidate_consumed("cand_yesterday_oct31")
    res3 = discovery.discover_candidates(count=1)
    # Stale candidate is skipped; discovery cascades to feed
    assert res3.candidates[0]["candidate_id"] != "cand_stale_oct15"


def test_sliding_window_fails_closed_when_all_topics_older_than_3_days(discovery_env):
    """When strict_news_only is active and all topics are older than 3 days, halts NO_ELIGIBLE_TOPIC."""
    simulated_run_date = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    stale_only = [
        {
            "candidate_id": "cand_old_oct10",
            "title": "Agent Testing Standard from Early October",
            "topic_family": "agent_evaluation",
            "canonical_url": "https://example.com/oct10",
            "summary": "Published 22 days ago.",
            "content_kind": "news",
            "is_evergreen": False,
            "published_at_utc": "2026-10-10T00:00:00Z",
        }
    ]
    curated_path = discovery_env["root"] / "data" / "stale_only.json"
    curated_path.write_text(json.dumps(stale_only, indent=2), encoding="utf-8")

    empty_feed = discovery_env["root"] / "data" / "empty_feed.json"
    empty_feed.write_text("[]", encoding="utf-8")

    discovery = HybridCandidateDiscovery(
        curated_path=curated_path,
        feed_path=empty_feed,
        root_dir=discovery_env["root"],
        require_latest_news=True,
        strict_news_only=True,
        max_age_days=3,
        reference_time=simulated_run_date,
    )

    res = discovery.discover_candidates(count=1)
    assert res.is_eligible is False
    assert res.tier == DiscoveryTier.NONE
    assert res.status == OutcomeStatus.NO_ELIGIBLE_TOPIC.value


