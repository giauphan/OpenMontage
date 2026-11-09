"""Test that live scraping failure seamlessly and deterministically falls back
to authorized source feeds and Tier 1 curated backlog without failing closed or writing blocking markers.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.hybrid_discovery import HybridCandidateDiscovery, DiscoveryTier


def test_hybrid_discovery_merges_sources_feed(tmp_path: Path):
    """Test that load_curated_candidates loads daily_candidates and merges authorized sources."""
    root = Path(__file__).resolve().parents[2]
    discovery = HybridCandidateDiscovery(root_dir=root)
    curated = discovery.load_curated_candidates()
    assert len(curated) >= 4, f"Expected at least 4 curated candidates, got {len(curated)}"
    
    # Check that candidates from production_agent_engineering_feed.json are present
    titles = [c.get("title", "") for c in curated]
    assert any("context window" in t.lower() or "requirements between sessions" in t.lower() for t in titles)


def test_produce_falls_back_to_curated_when_live_feed_off_niche(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When newsnow_feed.json has only off-niche items, produce hydrates from hybrid discovery."""
    from tools.news.news_pipeline_cli import main
    from datetime import datetime, timezone

    # Simulate a live newsnow feed with only off-niche stories
    off_niche_feed = [
        {
            "id": f"story_{i}",
            "title": f"Celebrity story {i} about fashion and travel",
            "url": f"https://gossip.example.com/story_{i}",
            "publisher": "Entertainment Tonight",
            "description": "Celebrities on vacation.",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(10)
    ]
    feed_file = tmp_path / "newsnow_feed.json"
    feed_file.write_text(json.dumps(off_niche_feed))

    marker_file = tmp_path / "data" / ".no_eligible_topic_marker"
    monkeypatch.setattr("tools.news.news_pipeline_cli.NO_ELIGIBLE_MARKER_PATH", marker_file)

    monkeypatch.setenv("MIN_PRODUCE_COUNT", "1")

    # Running produce on newsnow_feed.json should hydrate from curated queue in dry-run mode
    # without raising SystemExit(2)
    try:
        main(["produce", "--input", str(feed_file), "--count", "1", "--dry-run"])
    except SystemExit as e:
        # Exit 0 is ok, exit 2 (NO_ELIGIBLE_TOPIC) is a failure
        assert e.code == 0, f"produce should not fail closed when curated fallback exists (exit code {e.code})"

    assert not marker_file.is_file(), "Blocking marker must NOT be created when curated fallback is available"
