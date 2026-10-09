"""Regression coverage for source-backed daily-news research generation."""

import pytest

from lib.codex_news_selector import CodexNewsSelector
from lib.news_research_bridge import NewsResearchBridge


def _schema_valid_draft():
    return {
        "landscape": {
            "existing_content": [
                {"title": f"Coverage {i}", "source": "news", "angle": "report", "what_it_covers": "Supplied story"}
                for i in range(1, 4)
            ],
            "saturated_angles": [],
            "underserved_gaps": ["Unanswered question"],
        },
        "data_points": [
            {"claim": f"Supplied claim {i}", "source_url": f"https://example.test/source-{i}", "credibility": "secondary_source"}
            for i in range(1, 4)
        ],
        "audience_insights": {
            "common_questions": ["Question one?", "Question two?", "Question three?"],
            "misconceptions": [{"myth": "Supplied myth", "reality": "Supplied supported reality"}],
            "knowledge_level": "intermediate",
        },
        "angles_discovered": [
            {"name": f"Supplied angle {i}", "hook": f"Supplied hook {i}", "type": "trending", "why_now": f"Supplied basis {i}"}
            for i in range(1, 4)
        ],
        "sources": [
            {"url": f"https://example.test/source-{i}", "title": f"Source {i}", "used_for": "data_points"}
            for i in range(1, 6)
        ],
    }


def _candidate(**overrides):
    candidate = {
        "candidate_id": "cand_1",
        "content_hash": "hash",
        "title": "A source title",
        "canonical_url": "https://example.test/story",
        "publisher": "Example",
        "raw_provenance": {"source_feed": "newsnow:example"},
    }
    candidate.update(overrides)
    return candidate


def test_algorithmic_fallback_does_not_make_up_claims_endorsements_or_sources():
    result = CodexNewsSelector()._fallback_selection([{
        "candidate_id": "cand_1",
        "title": "A source title",
        "summary": "Supplied source summary",
        "url": "https://example.test/story",
        "source": "Example",
    }])
    draft = result["research_draft"]

    assert result["research_status"] == "incomplete"
    assert draft["data_points"] == [{
        "claim": "Supplied source summary",
        "source_url": "https://example.test/story",
        "credibility": "anecdotal",
    }]
    assert draft["landscape"] == {
        "existing_content": [],
        "saturated_angles": [],
        "underserved_gaps": [],
    }
    assert draft["angles_discovered"] == []
    assert draft["audience_insights"]["common_questions"] == []
    assert draft["audience_insights"]["misconceptions"] == []
    assert draft["sources"] == [{
        "url": "https://example.test/story",
        "title": "A source title",
        "used_for": "Candidate source; not independently researched",
    }]


def test_insufficient_fallback_evidence_is_explicitly_blocked():
    result = CodexNewsSelector()._fallback_selection([{
        "candidate_id": "cand_1",
        "title": "A source title",
        "summary": "Supplied source summary",
        "url": "https://example.test/story",
    }])

    with pytest.raises(ValueError, match=r"BLOCKED: research incomplete.*three supplied existing_content records"):
        NewsResearchBridge().build_brief(
            {"candidate_id": "cand_1", "content_hash": "hash", "title": "A source title"},
            result,
        )


def test_empty_claims_are_blocked_not_padded():
    draft = _schema_valid_draft()
    draft["data_points"] = []
    with pytest.raises(ValueError, match=r"BLOCKED: research incomplete.*three supplied source-backed data_points"):
        NewsResearchBridge().build_brief(_candidate(), {"research_draft": draft})


def test_missing_misconception_reality_is_rejected_not_replaced():
    draft = _schema_valid_draft()
    draft["audience_insights"]["misconceptions"][0].pop("reality")
    with pytest.raises(ValueError, match="misconception reality must be a non-empty string"):
        NewsResearchBridge().build_brief(_candidate(), {"research_draft": draft})


def test_fallback_does_not_create_evidence_without_url_or_nonempty_summary():
    result = CodexNewsSelector()._fallback_selection([{
        "candidate_id": "cand_1",
        "title": "A source title",
        "summary": "   ",
    }])
    draft = result["research_draft"]

    assert result["research_status"] == "incomplete"
    assert draft["data_points"] == []
    assert draft["sources"] == []
    assert draft["landscape"] == {
        "existing_content": [],
        "saturated_angles": [],
        "underserved_gaps": [],
    }
    assert draft["angles_discovered"] == []


def test_bridge_requires_five_distinct_supplied_source_records():
    draft = _schema_valid_draft()
    draft["sources"][-1]["url"] = draft["sources"][0]["url"]

    with pytest.raises(ValueError, match="BLOCKED: research incomplete; fewer than five supplied source records"):
        NewsResearchBridge().build_brief(_candidate(), {"research_draft": draft})


def test_bridge_accepts_five_distinct_supplied_source_records():
    brief = NewsResearchBridge().build_brief(
        _candidate(), {"research_draft": _schema_valid_draft()}
    )

    assert len(brief["data_points"]) == 3
    assert len(brief["sources"]) == 5
    assert len({source["url"] for source in brief["sources"]}) == 5


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("landscape", "existing_content"), [], "existing_content records"),
        (("landscape", "underserved_gaps"), [], "no supplied underserved_gaps"),
        (("audience_insights", "common_questions"), [], "common_questions"),
        (("angles_discovered",), [], "angles_discovered"),
    ],
)
def test_bridge_blocks_missing_research_instead_of_padding(path, value, message):
    draft = _schema_valid_draft()
    node = draft
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        NewsResearchBridge().build_brief(_candidate(), {"research_draft": draft})
