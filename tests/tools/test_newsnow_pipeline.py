"""Focused tests for NewsNow pipeline contracts."""

import argparse
import datetime
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.claude_news_selector import ClaudeNewsSelector
from lib.news_research_bridge import NewsResearchBridge
from lib.news_scoring import NewsCandidateScorer
from tools.news.newsnow_adapter import NewsNowAdapter
from tools.news import news_pipeline_cli, newsnow_feed


URLS = [f"https://example.com/{number}" for number in range(1, 6)]


def candidate(number: int) -> dict:
    return {
        "candidate_id": f"c{number}",
        "canonical_url": URLS[number - 1],
        "original_url": URLS[number - 1],
        "title": f"Article {number}",
        "publisher": "Example",
        "normalized_publisher": "example",
        "published_at_utc": "2026-08-10T10:00:00+00:00",
        "content_hash": f"hash{number}",
        "raw_provenance": {"source_id": str(number)},
    }


def research_draft() -> dict:
    return {
        "research_draft": {
            "landscape": {
                "existing_content": [
                    {"title": f"Existing {number}", "url": URLS[number - 1], "source": "news", "angle": "explainer", "what_it_covers": "Topic coverage"}
                    for number in range(1, 4)
                ],
                "saturated_angles": ["Generic summary"],
                "underserved_gaps": ["Practical impact"],
            },
            "data_points": [
                {"claim": f"Claim {number}", "source_url": URLS[number - 1], "credibility": "primary_source"}
                for number in range(1, 4)
            ],
            "audience_insights": {
                "common_questions": ["What changed?", "Why now?", "Who is affected?"],
                "misconceptions": [{"myth": "It has no impact.", "reality": "It has measurable impact."}],
                "knowledge_level": "intermediate",
            },
            "angles_discovered": [
                {"name": f"Angle {number}", "hook": f"Hook {number}", "type": "trending", "why_now": "Recent development."}
                for number in range(1, 4)
            ],
            "sources": [
                {"url": URLS[number - 1], "title": f"Article {number}", "used_for": "Research grounding"}
                for number in range(1, 6)
            ],
        }
    }


def test_adapter_invalid_timestamp_structured_diagnostics():
    adapter = NewsNowAdapter()
    raw_items = [{"id": "bad", "title": "Title", "url": URLS[0], "published_at": "not-a-date", "publisher": "Example"}]

    candidates, diagnostics = adapter.ingest_and_normalize(raw_items)

    assert candidates == []
    assert diagnostics == [{
        "raw_item_id": "bad",
        "reason": "invalid_iso_timestamp",
        "error": "Invalid timestamp format: not-a-date",
        "field": "published_at",
        "raw_value": "not-a-date",
    }]


@pytest.mark.parametrize(
    "include_published_at,published_at,expected_raw_value",
    [(False, None, "missing"), (True, None, None), (True, "", ""), (True, "   ", "   ")],
)
def test_adapter_rejects_unknown_publication_time(include_published_at, published_at, expected_raw_value):
    item = {"id": "undated", "title": "Title", "url": URLS[0], "publisher": "Example"}
    if include_published_at:
        item["published_at"] = published_at

    candidates, diagnostics = NewsNowAdapter().ingest_and_normalize(
        [item], reference_time=datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc)
    )

    assert candidates == []
    assert diagnostics == [{
        "raw_item_id": "undated",
        "reason": "unknown_published_at",
        "field": "published_at",
        "raw_value": expected_raw_value,
    }]


def test_adapter_reports_non_object_items_and_processes_valid_items():
    valid_item = {
        "id": "valid",
        "title": "Valid story",
        "url": URLS[0],
        "publisher": "Example",
        "published_at": "2026-08-10T10:00:00Z",
    }

    candidates, diagnostics = NewsNowAdapter().ingest_and_normalize(
        [None, "not-an-object", valid_item],
        reference_time=datetime.datetime(2026, 8, 10, 12, tzinfo=datetime.timezone.utc),
    )

    assert [candidate["title"] for candidate in candidates] == ["Valid story"]
    assert diagnostics == [
        {
            "raw_item_id": "missing_id",
            "reason": "invalid_format",
            "error": "Raw item must be an object",
        },
        {
            "raw_item_id": "missing_id",
            "reason": "invalid_format",
            "error": "Raw item must be an object",
        },
    ]


def test_adapter_rejects_future_publication_time():
    candidates, diagnostics = NewsNowAdapter().ingest_and_normalize(
        [{"id": "future", "title": "Title", "url": URLS[0], "publisher": "Example", "published_at": "2026-08-11T00:00:00Z"}],
        reference_time=datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc),
    )

    assert candidates == []
    assert diagnostics == [{
        "raw_item_id": "future",
        "reason": "future_published_at",
        "field": "published_at",
        "raw_value": "2026-08-11T00:00:00Z",
    }]


def test_scoring_axis_keys_and_stable_tie_break():
    scorer = NewsCandidateScorer(reference_time=datetime.datetime(2026, 8, 10, 12, tzinfo=datetime.timezone.utc))
    first = candidate(1)
    second = candidate(2)
    first["candidate_id"] = "a"
    second["candidate_id"] = "b"

    ranked = scorer.rank_candidates([second, first], limit=2)

    assert [item["candidate_id"] for item in ranked] == ["a", "b"]
    assert ranked[0]["scoring"]["axes"] == {
        "freshness": 1.0,
        "publisher_authority": 0.5,
        "fact_density": 0.4,
        "visual_potential": 0.3,
        "audience_interest": 0.05,
        "feasibility": 1.0,
    }


def test_selector_rejects_foreign_source_url_and_shells_out_with_print():
    selector = ClaudeNewsSelector(cli_path="claude-test")
    candidates = [candidate(number) for number in range(1, 6)]
    valid = {"selected_candidate_id": "c1", "selection_rationale": "Good fit", **research_draft()}

    assert selector._validate_output(valid, candidates) == valid

    foreign = {"selected_candidate_id": "c1", "selection_rationale": "Bad source", **research_draft()}
    foreign["research_draft"]["sources"][0]["url"] = "https://foreign.example/article"
    assert selector._validate_output(foreign, candidates) is None

    with patch("os.geteuid", return_value=1000):
        with patch("lib.claude_news_selector.subprocess.run") as run:
            run.return_value.stdout = "{}"
            selector._run_claude("prompt")

    assert run.call_args.args[0] == [
        "bash",
        "-c",
        "env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT -u CLAUDE_SESSION_ID -u ANTHROPIC_MODEL claude-test -p --model claude-opus-4-7 prompt",
    ]


def test_selector_extracts_markdown_wrapped_json():
    selector = ClaudeNewsSelector()

    with patch("lib.claude_news_selector.subprocess.run") as run:
        run.return_value.stdout = '```json\n{"selected_candidate_id": "c1"}\n```'
        assert selector._run_claude("prompt") == {"selected_candidate_id": "c1"}


def test_bridge_emits_canonical_schema_without_duplicate_urls():
    bridge = NewsResearchBridge()
    brief = bridge.build_brief(candidate(1), research_draft())

    assert brief["version"] == "1.0"
    assert brief["topic"] == "Article 1"
    assert len(brief["landscape"]["existing_content"]) == 3
    assert len(brief["data_points"]) == 3
    assert len(brief["angles_discovered"]) == 3
    assert len(brief["sources"]) == 5
    assert len({source["url"] for source in brief["sources"]}) == 5


def test_bridge_blocks_when_supplied_sources_do_not_meet_schema_minimum():
    bridge = NewsResearchBridge()
    incomplete = research_draft()
    incomplete["research_draft"]["sources"] = incomplete["research_draft"]["sources"][:4]

    with pytest.raises(ValueError, match="BLOCKED: research incomplete; fewer than five supplied source records"):
        bridge.build_brief(candidate(1), incomplete)


def _newsnow_payload(source: str, count: int) -> dict:
    return {
        "status": "success",
        "id": source,
        "updatedTime": 1787237127958,
        "items": [
            {"url": f"https://{source}.example/{number}", "title": f"{source} story {number}", "id": str(number), "extra": {"info": "100 points"}}
            for number in range(count)
        ],
    }


def test_produce_retries_rejected_research_candidate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SKIP_SCOPE_GATE", "1")
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    published_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    feed = [{
        "id": f"item{number}",
        "url": URLS[number - 1],
        "title": f"Article {number}",
        "publisher": "Example",
        "published_at": published_at,
        "description": "Source-backed summary about technology development and artificial intelligence innovation.",
    } for number in range(1, 6)]
    Path("data/newsnow_feed.json").write_text(json.dumps(feed), encoding="utf-8")

    adapter = NewsNowAdapter()
    candidates, _ = adapter.ingest_and_normalize(feed)
    c1_id = candidates[0]["candidate_id"]
    c2_id = candidates[1]["candidate_id"]

    selections = [
        {"selected_candidate_id": c1_id, "research_draft": {"landscape": {"existing_content": []}}},
        {"selected_candidate_id": c2_id, "selection_rationale": "valid", **research_draft()},
    ]

    class Selector:
        def select_and_research(self, _pool):
            return selections.pop(0)

    monkeypatch.setattr(news_pipeline_cli, "NewsSelector", lambda: Selector())
    news_pipeline_cli.run_produce(argparse.Namespace(input="data/newsnow_feed.json", count=1, dry_run=False))

    captured = capsys.readouterr().out
    assert f"PROJECT_ID={c2_id}" in captured
    assert (tmp_path / f"projects/{c2_id}/artifacts/research_brief.json").exists()


def test_feed_converter_normalizes_and_dedupes(monkeypatch):
    raw_feed_items = [
        {
            "id": "newsnow_hn_1",
            "url": "https://docs.anthropic.com/agent-tools",
            "title": "Model Context Protocol Tool Schema Update",
            "publisher": "Anthropic",
            "published_at": "2026-08-10T10:00:00Z",
            "description": "Dynamic tool scoping specifications for multi-server MCP environments.",
            "body": "Dynamic tool scoping specifications for multi-server MCP environments.",
            "tags": ["hackernews"],
            "extra": {"retrieved_at": "2026-08-10T11:00:00Z"},
        },
        {
            "id": "newsnow_gh_1",
            "url": "https://docs.anthropic.com/agent-tools",  # duplicate URL to test dedupe
            "title": "Model Context Protocol Tool Schema Update",
            "publisher": "Anthropic",
            "published_at": "2026-08-10T10:00:00Z",
            "description": "Duplicate feed entry",
            "body": "Duplicate feed entry",
            "tags": ["github"],
            "extra": {"retrieved_at": "2026-08-10T11:00:00Z"},
        },
        {
            "id": "newsnow_hn_2",
            "url": "https://github.com/swe-bench/eval",
            "title": "SWE-bench Evaluation Suite Update",
            "publisher": "GitHub",
            "tags": ["hackernews"],
            "extra": {"retrieved_at": "2026-08-10T11:00:00Z"},
        },
    ]

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"count": len(raw_feed_items), "items": raw_feed_items}).encode("utf-8")

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", lambda req, timeout=0: _Response())
    items = newsnow_feed.fetch_feed("http://127.0.0.1:20129/custom/daily-news")

    urls = [item["url"] for item in items]
    assert len(urls) == len(set(urls))
    dated = next(item for item in items if "published_at" in item)
    undated = next(item for item in items if "published_at" not in item)
    assert dated["published_at"] == "2026-08-10T10:00:00Z"
    assert "retrieved_at" in dated["extra"]
    assert "retrieved_at" in undated["extra"]
    candidates, diagnostics = NewsNowAdapter().ingest_and_normalize(
        items, reference_time=datetime.datetime(2026, 8, 10, 12, tzinfo=datetime.timezone.utc)
    )
    assert len(candidates) == 1
    assert sum(diagnostic["reason"] == "unknown_published_at" for diagnostic in diagnostics) == len(items) - 1


def test_feed_write_requires_minimum(monkeypatch, tmp_path):
    monkeypatch.setattr(newsnow_feed, "fetch_feed", lambda url, *a, **k: [{"id": "1"}])
    with pytest.raises(RuntimeError, match="need at least 3"):
        newsnow_feed.write_feed("http://127.0.0.1:20129/custom/daily-news", tmp_path / "feed.json", minimum=3)


def test_produce_hydrates_from_hybrid_discovery_when_input_insufficient(tmp_path):
    args = argparse.Namespace(
        count=3,
        require_latest_news=True,
        max_age_days=7,
    )
    initial_pool = []
    used_ids = set()
    hydrated = news_pipeline_cli._hydrate_from_hybrid_discovery(
        initial_pool, count=3, min_required=3, used_ids=used_ids, args=args
    )
    assert len(hydrated) >= 3
    for c in hydrated:
        assert c.get("candidate_id") is not None
        assert c.get("topic_family") in {
            "agent_tool_use", "context_memory", "agent_architecture",
            "agent_evaluation", "debugging_reliability"
        }


def test_hydrate_from_hybrid_discovery_fallback_trigger(monkeypatch):
    """Test _run_discovery_fallback when discovery initially yields insufficient candidates."""
    class FakeResult:
        def __init__(self, candidates, status="ELIGIBLE"):
            self.candidates = candidates
            self.status = status

        @property
        def is_eligible(self) -> bool:
            return self.status == "ELIGIBLE" and len(self.candidates) > 0

    call_count = 0

    class MockDiscovery:
        def __init__(self, require_latest_news=True, max_age_days=7):
            self.require_latest_news = require_latest_news

        def discover_candidates(self, count=1):
            nonlocal call_count
            call_count += 1
            if self.require_latest_news:
                # 0 candidates initially
                return FakeResult(candidates=[], status="INSUFFICIENT")
            # fallback returns candidates
            return FakeResult(candidates=[{"candidate_id": "fb_1"}], status="ELIGIBLE")

    monkeypatch.setattr("lib.fixed_niche.hybrid_discovery.HybridCandidateDiscovery", MockDiscovery)

    args = argparse.Namespace(require_latest_news=True, max_age_days=7)
    pool = []
    hydrated = news_pipeline_cli._hydrate_from_hybrid_discovery(
        pool, count=1, min_required=1, used_ids=set(), args=args
    )
    assert len(hydrated) == 1
    assert hydrated[0]["candidate_id"] == "fb_1"
    assert call_count == 2


