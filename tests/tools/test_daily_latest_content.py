from datetime import datetime, timedelta, timezone
import argparse
import pytest

from tools.news import news_pipeline_cli as cli
from tools.news.news_pipeline_cli import _filter_fresh_candidates


def test_freshness_rejects_old_missing_invalid_and_future_dates():
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    items = [
        {"candidate_id": "fresh", "published_at": (now - timedelta(hours=2)).isoformat()},
        {"candidate_id": "old", "published_at": (now - timedelta(hours=25)).isoformat()},
        {"candidate_id": "missing"},
        {"candidate_id": "invalid", "published_at": "unknown"},
        {"candidate_id": "future", "published_at": (now + timedelta(hours=1)).isoformat()},
    ]
    assert [c["candidate_id"] for c in _filter_fresh_candidates(items, 24, now)] == ["fresh"]


def test_producer_rejects_stale_input_before_selection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    (tmp_path / "newsnow_feed.json").write_text("[]")
    monkeypatch.setattr(cli, "_collect_used_project_ids", lambda: set())
    monkeypatch.setattr(cli, "_ingest_and_filter_candidates", lambda *a, **k: [
        {"candidate_id": "old", "published_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}
    ])
    def hydrate(pool, *args):
        assert pool == []  # Stale input must not prevent discovery of fresh alternatives.
        return pool

    monkeypatch.setattr(cli, "_hydrate_from_hybrid_discovery", hydrate)
    args = argparse.Namespace(input="newsnow_feed.json", count=1, require_latest_news=True, max_age_days=7, dry_run=True)
    with pytest.raises(SystemExit) as exc:
        cli.run_produce(args)
    assert exc.value.code == 2


def test_used_candidates_are_not_reintroduced_when_pool_is_small(monkeypatch, tmp_path):
    from tools.news.newsnow_adapter import NewsNowAdapter
    import json
    raw = {"id": "used", "url": "https://example.org/update", "title": "MCP tool call change",
           "published_at": datetime.now(timezone.utc).isoformat(), "source_feed": "muse"}
    path = tmp_path / "feed.json"
    path.write_text(json.dumps([raw]))
    used = NewsNowAdapter().normalize_item(raw)["candidate_id"]
    monkeypatch.setenv("SKIP_SCOPE_GATE", "1")
    assert cli._ingest_and_filter_candidates(path, count=3, used_ids={used}, fail_closed=False) == []


def test_ingest_honors_configured_freshness_window(monkeypatch, tmp_path):
    """The initial adapter pass must not silently cap a configured freshness policy at 48h."""
    import json

    published = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    path = tmp_path / "feed.json"
    path.write_text(json.dumps([{
        "id": "within-configured-window",
        "url": "https://example.org/latest-agent-update",
        "title": "Agent engineering update",
        "published_at": published,
        "source_feed": "muse",
    }]))
    monkeypatch.setenv("SKIP_SCOPE_GATE", "1")

    result = cli._ingest_and_filter_candidates(
        path, count=1, used_ids=set(), fail_closed=False, freshness_window_hours=168,
    )

    assert [candidate["title"] for candidate in result] == ["Agent engineering update"]


def test_muse_history_survives_project_cleanup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    candidate_id = "cand_0123456789abcdef"
    assert cli.main(["mark-muse-used", "--candidate-id", candidate_id]) == 0
    assert candidate_id in cli._collect_used_project_ids()
    assert cli.main(["mark-muse-used", "--candidate-id", candidate_id]) == 0
