"""Unit tests for Toolcase Gateway Daily News Client.

Covers:
- URL resolution with TOOLCASE_GATEWAY_URL, DAILY_NEWS_GATEWAY_URL, and direct inputs.
- Scheme, port normalization, and SSRF hostname boundary validation.
- Health check probing.
- Latest news feed fetching, parameter propagation, and item normalization.
- Tiered discovery query and payload dispatch.
- Candidate consumption / removal logic (POST /custom/daily-news/api/v1/consume).
- Atomic feed persistence (write_feed).
- Error handling on unparseable responses or connection failure.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError

import pytest

from tools.news.daily_news_gateway import (
    DEFAULT_GATEWAY_NAMESPACE,
    DEFAULT_SOURCES,
    DEFAULT_TOOLCASE_GATEWAY_PORT,
    DEFAULT_TOOLCASE_GATEWAY_URL,
    DailyNewsGatewayClient,
    _resolve_safe_output_path,
    _sanitize_log_val,
    resolve_gateway_base_url,
)
from tools.news import newsnow_feed
from tools.news import news_pipeline_cli
from lib.fixed_niche.hybrid_discovery import HybridCandidateDiscovery


class FakeHttpResponse:
    def __init__(self, data: Any, status: int = 200) -> None:
        self.data = data
        self.status = status

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self) -> bytes:
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data).encode("utf-8")
        return str(self.data).encode("utf-8")


@pytest.fixture(autouse=True)
def _clean_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TOOLCASE_GATEWAY_URL",
        "DAILY_NEWS_GATEWAY_BASE_URL",
        "DAILY_NEWS_GATEWAY_URL",
        "DAILY_NEWS_URL",
        "NEWSNOW_API_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_resolve_gateway_base_url_default():
    url = resolve_gateway_base_url()
    assert url == f"{DEFAULT_TOOLCASE_GATEWAY_URL}{DEFAULT_GATEWAY_NAMESPACE}"


def test_resolve_gateway_base_url_from_toolcase_env(monkeypatch):
    monkeypatch.setenv("TOOLCASE_GATEWAY_URL", "http://10.0.0.5:20129")
    url = resolve_gateway_base_url()
    assert url == "http://10.0.0.5:20129/custom/daily-news"


def test_resolve_gateway_base_url_from_daily_news_env(monkeypatch):
    monkeypatch.setenv("DAILY_NEWS_GATEWAY_URL", "http://127.0.0.1:20129/custom/daily-news")
    url = resolve_gateway_base_url()
    assert url == "http://127.0.0.1:20129/custom/daily-news"


def test_resolve_gateway_base_url_from_newsnow_api_env(monkeypatch):
    monkeypatch.setenv("NEWSNOW_API_URL", "http://127.0.0.1:20129")
    url = resolve_gateway_base_url()
    assert url == "http://127.0.0.1:20129/custom/daily-news"


def test_resolve_gateway_base_url_port_normalization():
    # If legacy test port 28130 is provided, normalize to 20129
    url = resolve_gateway_base_url("http://127.0.0.1:28130")
    assert f":{DEFAULT_TOOLCASE_GATEWAY_PORT}" in url
    assert url.endswith(DEFAULT_GATEWAY_NAMESPACE)


def test_resolve_gateway_base_url_invalid_scheme():
    with pytest.raises(ValueError, match="Invalid Daily News Gateway URL scheme"):
        resolve_gateway_base_url("ftp://127.0.0.1:20129")


def test_resolve_gateway_base_url_missing_hostname():
    with pytest.raises(ValueError, match="Missing hostname"):
        resolve_gateway_base_url("http://")


def test_check_health_success(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    payload = {"status": "healthy", "module": "daily-news", "version": "1.3.0", "consumed_count": 2}
    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", lambda req, timeout=0: FakeHttpResponse(payload))

    res = client.check_health()
    assert res["status"] == "healthy"
    assert res["version"] == "1.3.0"
    assert res["consumed_count"] == 2


def test_check_health_failure(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")

    def failing_urlopen(*args, **kwargs):
        raise URLError("Connection refused")

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", failing_urlopen)
    res = client.check_health()
    assert res["status"] == "unhealthy"
    assert "error" in res


def test_check_health_fallback_root(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if req.full_url.endswith("/custom/daily-news/health"):
            raise HTTPError(req.full_url, 404, "Not Found", {}, None)
        return FakeHttpResponse({"status": "healthy", "service": "root"})

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", fake_urlopen)
    res = client.check_health()
    assert res["status"] == "healthy"
    assert "http://127.0.0.1:20129/health" in calls


def test_fetch_feed_successful(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    raw_payload = {
        "count": 2,
        "items": [
            {
                "id": "hn_101",
                "url": "https://docs.anthropic.com/agent-tools",
                "title": "MCP Tool Spec",
                "published_at": "2026-11-02T10:00:00Z",
            },
            {
                "id": "hn_102",
                "url": "https://modelcontextprotocol.io/spec",
                "title": "Model Context Protocol Documentation",
                "published_at": "2026-11-02T11:00:00Z",
            },
        ],
    }
    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", lambda req, timeout=0: FakeHttpResponse(raw_payload))

    items = client.fetch_feed(limit=5)
    assert len(items) == 2
    assert items[0]["id"] == "hn_101"
    assert items[0]["publisher"] == "docs.anthropic.com"
    assert "retrieved_at" in items[0]["extra"]


def test_fetch_feed_deduplication(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    raw_payload = [
        {"id": "1", "url": "https://example.com/item1", "title": "Item 1", "published_at": "2026-11-01"},
        {"id": "2", "url": "https://example.com/item1/", "title": "Item 1 Duplicate", "published_at": "2026-11-01"},
    ]
    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", lambda req, timeout=0: FakeHttpResponse(raw_payload))

    items = client.fetch_feed()
    assert len(items) == 1
    assert items[0]["id"] == "1"


def test_fetch_feed_error_propagation(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")

    def failing_urlopen(*args, **kwargs):
        raise URLError("Gateway down")

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", failing_urlopen)
    with pytest.raises(RuntimeError, match="Failed to fetch feed from Daily News Gateway"):
        client.fetch_feed()


def test_discover_candidates_request(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    captured_req = {}

    def fake_urlopen(req, timeout=0):
        captured_req["url"] = req.full_url
        captured_req["data"] = json.loads(req.data.decode("utf-8"))
        return FakeHttpResponse({
            "tier": "tier_2_automated",
            "status": "ELIGIBLE",
            "count": 1,
            "candidates": [{"candidate_id": "cand_1", "title": "Discovered Story"}],
        })

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", fake_urlopen)
    res = client.discover_candidates(
        limit=2,
        from_date="2026-11-01",
        to_date="2026-11-02",
        topics=["agent_tool_use"],
        sources=["hackernews"],
    )
    assert res["status"] == "ELIGIBLE"
    assert res["count"] == 1
    assert captured_req["data"]["limit"] == 2
    assert captured_req["data"]["from_date"] == "2026-11-01"
    assert captured_req["data"]["topics"] == ["agent_tool_use"]


def test_consume_candidates_removal_logic(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    captured_payload = {}

    def fake_urlopen(req, timeout=0):
        captured_payload["endpoint"] = req.full_url
        captured_payload["body"] = json.loads(req.data.decode("utf-8"))
        return FakeHttpResponse({"status": "consumed", "count": 2})

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", fake_urlopen)
    res = client.consume_candidates(["cand_1", "cand_2"])
    assert res["status"] == "consumed"
    assert res["count"] == 2
    assert captured_payload["endpoint"].endswith("/api/v1/consume")
    assert captured_payload["body"]["candidate_ids"] == ["cand_1", "cand_2"]


def test_consume_candidates_preserves_long_id(monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    captured_payload = {}
    long_id = "agent_candidate_" + "x" * 120

    def fake_urlopen(req, timeout=0):
        captured_payload["body"] = json.loads(req.data.decode("utf-8"))
        return FakeHttpResponse({"status": "consumed", "count": 1})

    monkeypatch.setattr("tools.news.daily_news_gateway.urlopen", fake_urlopen)
    res = client.consume_candidates([long_id])
    assert res["status"] == "consumed"
    assert captured_payload["body"]["candidate_ids"] == [long_id]


def test_consume_candidates_empty_noop():
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    res = client.consume_candidates([])
    assert res == {"status": "consumed", "count": 0}


def test_write_feed_atomic_write(tmp_path, monkeypatch):
    client = DailyNewsGatewayClient("http://127.0.0.1:20129/custom/daily-news")
    items = [
        {"id": f"id_{i}", "url": f"https://example.com/{i}", "title": f"T{i}", "published_at": "2026-11-01"}
        for i in range(4)
    ]
    monkeypatch.setattr(client, "fetch_feed", lambda *a, **k: items)
    out_file = tmp_path / "data" / "feed.json"
    written_count = client.write_feed(output=out_file, minimum=3)
    assert written_count == 4
    assert out_file.is_file()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(saved) == 4


def test_hybrid_discovery_mark_consumed_syncs_to_gateway(tmp_path, monkeypatch):
    consumed_on_gw = []

    def mock_consume(self, cids, base_url=None):
        consumed_on_gw.extend(cids)
        return {"status": "consumed", "count": len(cids)}

    monkeypatch.setattr(DailyNewsGatewayClient, "consume_candidates", mock_consume)
    curated = tmp_path / "daily_candidates.json"
    curated.write_text("[]", encoding="utf-8")
    feed = tmp_path / "newsnow_feed.json"
    feed.write_text("[]", encoding="utf-8")

    disc = HybridCandidateDiscovery(
        curated_path=curated,
        feed_path=feed,
        root_dir=tmp_path,
    )
    disc.mark_candidate_consumed("cand_mcp_scoping")
    assert "cand_mcp_scoping" in consumed_on_gw


def test_news_pipeline_cli_fetch_defaults_to_gateway(tmp_path, monkeypatch):
    called_url = []

    def mock_write_feed(base_url=None, output=None, minimum=3, **kwargs):
        called_url.append(base_url)
        return 5

    monkeypatch.setattr(news_pipeline_cli, "write_feed", mock_write_feed)
    args = argparse.Namespace(
        command="fetch",
        url=None,
        output=str(tmp_path / "feed.json"),
        min_items=3,
    )
    news_pipeline_cli.run_fetch(args)
    assert len(called_url) == 1
    assert called_url[0] is None  # Auto-resolves via TOOLCASE_GATEWAY_URL


def test_newsnow_feed_consume_candidates_delegation(monkeypatch):
    consumed = []

    def mock_consume(self, candidate_ids, base_url=None):
        consumed.extend(candidate_ids)
        return {"status": "consumed", "count": len(candidate_ids)}

    monkeypatch.setattr(DailyNewsGatewayClient, "consume_candidates", mock_consume)
    res = newsnow_feed.consume_candidates(["cand_direct_feed_api"])
    assert res["status"] == "consumed"
    assert "cand_direct_feed_api" in consumed


def test_sanitize_log_val_removes_newlines_and_control_chars():
    dirty = "candidate_1\r\ninjected_log_line\x00extra"
    cleaned = _sanitize_log_val(dirty)
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert "\x00" not in cleaned
    assert "injected_log_line" in cleaned


def test_resolve_safe_output_path_rejects_traversal():
    with pytest.raises(ValueError, match="Path traversal detected or path outside allowed root"):
        _resolve_safe_output_path("/etc/shadow")

    with pytest.raises(ValueError, match="Path traversal detected or path outside allowed root"):
        _resolve_safe_output_path("../../etc/passwd")


def test_resolve_safe_output_path_accepts_valid_paths(tmp_path):
    safe_tmp = tmp_path / "feed.json"
    resolved_tmp = _resolve_safe_output_path(safe_tmp)
    assert resolved_tmp == safe_tmp.resolve()

    safe_rel = Path("data/newsnow_feed.json")
    resolved_rel = _resolve_safe_output_path(safe_rel)
    assert resolved_rel == (Path.cwd() / safe_rel).resolve()

