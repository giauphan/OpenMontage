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
from tools.news import newsnow_feed


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

    assert run.call_args.args[0] == ["bash", "-c", "claude-test -p prompt"]


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


def test_bridge_pads_sources_to_schema_minimum():
    bridge = NewsResearchBridge()
    incomplete = research_draft()
    incomplete["research_draft"]["sources"] = incomplete["research_draft"]["sources"][:4]

    brief = bridge.build_brief(candidate(1), incomplete)

    assert len(brief["sources"]) == 5
    assert len({source["url"] for source in brief["sources"]}) == 5


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


def test_feed_converter_normalizes_and_dedupes(monkeypatch):
    payloads = {
        "hackernews": _newsnow_payload("hackernews", 2),
        "github": _newsnow_payload("github", 2),
        "producthunt": _newsnow_payload("producthunt", 0),
    }
    # Inject a cross-source duplicate URL to verify dedupe.
    payloads["github"]["items"][0]["url"] = payloads["hackernews"]["items"][0]["url"]

    def fake_urlopen(request, timeout=0):
        source = request.full_url.split("id=")[1]

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(payloads[source]).encode()

        return _Response()

    monkeypatch.setattr(newsnow_feed, "urlopen", fake_urlopen)
    items = newsnow_feed.fetch_feed("http://127.0.0.1:4444")

    urls = [item["url"] for item in items]
    assert len(urls) == len(set(urls))
    for item in items:
        assert item["id"] and item["url"] and item["title"] and item["published_at"]
        assert item["published_at"].endswith("+00:00")
    candidates, diagnostics = NewsNowAdapter().ingest_and_normalize(items)
    assert diagnostics == []
    assert len(candidates) == len(items)


def test_feed_write_requires_minimum(monkeypatch, tmp_path):
    monkeypatch.setattr(newsnow_feed, "fetch_feed", lambda url, *a, **k: [{"id": "1"}])
    with pytest.raises(RuntimeError, match="need at least 3"):
        newsnow_feed.write_feed("http://127.0.0.1:4444", tmp_path / "feed.json", minimum=3)

