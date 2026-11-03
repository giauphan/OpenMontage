import json
import argparse
from datetime import datetime, timezone

import pytest

from tools.news.muse_news import MuseNewsError, discover_news
from tools.news.newsnow_adapter import NewsNowAdapter
from tools.news import news_pipeline_cli as cli
from lib.codex_news_selector import CodexNewsSelector


NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


class Chat:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def chat(self, context_key, prompt):
        self.calls.append((context_key, prompt))
        return self.value


def item(url="https://example.org/changelog", timestamp="2026-11-03T10:00:00Z"):
    return {"id": "source-1", "url": url, "title": "Coding agent tool call changes", "published_at": timestamp,
            "publisher": "Example", "description": "An agent tool call contract changed."}


def test_discovery_emits_existing_feed_contract_and_editorial_prompt():
    chat = Chat(json.dumps([item(), item(), item("https://example.org/old", "2026-11-01T10:00:00Z"), item("https://example.org/future", "2026-11-04T10:00:00Z")]))
    result = discover_news(chat, max_age_hours=24, now=NOW)
    assert len(result) == 1
    assert result[0]["source_feed"] == "muse"
    assert result[0]["published_at"] == "2026-11-03T10:00:00Z"
    assert NewsNowAdapter().normalize_item(result[0])["canonical_url"] == item()["url"]
    assert chat.calls[0][0] == "us-ai-agent-engineering:news-discovery"
    assert "primary" in chat.calls[0][1].lower()
    assert "visual" in chat.calls[0][1].lower()
    assert "2026-11-03" in chat.calls[0][1]


@pytest.mark.parametrize("payload", ["not json", "{}", '[{"title":"missing fields"}]', json.dumps([item("http://example.org/a")]), json.dumps([item(timestamp="unknown")]), json.dumps([item(timestamp="2026-11-03T10:00:00")])])
def test_discovery_rejects_malformed_or_unusable_output(payload):
    with pytest.raises(MuseNewsError):
        discover_news(Chat(payload), max_age_hours=24, now=NOW)


def test_empty_array_is_a_valid_no_news_result():
    assert discover_news(Chat("[]"), max_age_hours=24, now=NOW) == []


def test_json_fence_is_accepted_without_accepting_extra_prose():
    assert len(discover_news(Chat("```json\n" + json.dumps([item()]) + "\n```"), max_age_hours=24, now=NOW)) == 1
    with pytest.raises(MuseNewsError):
        discover_news(Chat("Here is your feed: []"), max_age_hours=24, now=NOW)


def test_fetch_command_writes_muse_leads_in_existing_format(monkeypatch, tmp_path):
    feed = tmp_path / "feed.json"
    state = tmp_path / "threads.json"
    monkeypatch.setenv("MUSE_THREAD_CACHE", str(state))
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    monkeypatch.setattr("tools.news.muse_chat.MuseChatClient", lambda *args, **kwargs: Chat("[]"))
    monkeypatch.setattr(cli, "write_feed", lambda *a, **k: pytest.fail("unexpected legacy network path"))
    args = argparse.Namespace(source="muse", url=None, output=str(feed), min_items=0)
    cli.run_fetch(args)
    assert json.loads(feed.read_text()) == []


def test_muse_error_does_not_replace_prior_feed(monkeypatch, tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text("[1]")
    monkeypatch.setenv("MUSE_THREAD_CACHE", str(tmp_path / "threads.json"))
    monkeypatch.setattr("tools.news.muse_chat.MuseChatClient", lambda *args, **kwargs: Chat("bad"))
    monkeypatch.setattr(cli, "write_feed", lambda *a, **k: pytest.fail("unexpected legacy network path"))
    args = argparse.Namespace(source="muse", url=None, output=str(feed), min_items=0)
    with pytest.raises(MuseNewsError):
        cli.run_fetch(args)
    assert feed.read_text() == "[1]"


def test_editorial_ideas_pass_to_research_as_untrusted_suggestions():
    raw = item()
    raw["extra"] = {"editorial": {"viewer_question": "Why does the tool call fail?", "visual_idea": "A labeled request and response diagram"}}
    normalized = NewsNowAdapter().normalize_item(raw)
    prompt = CodexNewsSelector()._build_prompt([normalized])
    assert "Why does the tool call fail?" in prompt
    assert "labeled request and response diagram" in prompt
    assert "untrusted" in prompt.lower()


def test_muse_candidate_identity_is_stable_when_editorial_summary_changes():
    first = item()
    first["source_feed"] = "muse"
    second = dict(first, title="A different headline for the same release", description="A new editorial summary.")
    adapter = NewsNowAdapter()
    assert adapter.normalize_item(first)["candidate_id"] == adapter.normalize_item(second)["candidate_id"]
