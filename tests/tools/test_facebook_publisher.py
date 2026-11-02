"""Unit tests for FacebookPublisher via Toolcase Gateway Adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.publishers.facebook_publisher import FacebookPublisher, DEFAULT_14_LANGUAGES, DEFAULT_GATEWAY_PORT
from tools.tool_registry import ToolRegistry


def test_facebook_publisher_discovered_in_registry():
    registry = ToolRegistry()
    registry.discover()
    assert "facebook_publisher" in registry._tools
    tool_cls = registry._tools["facebook_publisher"]
    assert tool_cls.capability == "publish"
    assert tool_cls.provider == "facebook"


def test_gateway_url_resolution(monkeypatch):
    tool = FacebookPublisher()
    monkeypatch.delenv("FACEBOOK_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("META_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLCASE_GATEWAY_URL", raising=False)

    assert tool.get_gateway_base_url() == "http://127.0.0.1:20129/custom/facebook"

    monkeypatch.setenv("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129")
    assert tool.get_gateway_base_url() == "http://127.0.0.1:20129/custom/facebook"

    monkeypatch.setenv("FACEBOOK_GATEWAY_BASE_URL", "http://localhost:20129/custom/facebook")
    assert tool.get_gateway_base_url() == "http://localhost:20129/custom/facebook"


def test_gateway_port_normalization_from_doc_example(monkeypatch):
    """Doc README example specifies port 28130, but port 20129 is required on server deployment."""
    tool = FacebookPublisher()
    monkeypatch.setenv("FACEBOOK_GATEWAY_BASE_URL", "http://127.0.0.1:28130/custom/facebook")
    assert tool.get_gateway_base_url() == "http://127.0.0.1:20129/custom/facebook"

    # Input override normalization
    res = tool.get_gateway_base_url({"gateway_url": "http://10.0.0.5:28130/custom/facebook"})
    assert res == "http://10.0.0.5:20129/custom/facebook"


def test_missing_and_invalid_inputs(tmp_path: Path):
    tool = FacebookPublisher()

    # Missing video_path
    res = tool.execute({})
    assert not res.success
    assert "video_path" in res.error

    # Non-existent file
    res = tool.execute({"video_path": str(tmp_path / "nonexistent.mp4"), "caption": "Tin tức"})
    assert not res.success
    assert "not found" in res.error

    # Missing caption
    v = tmp_path / "vid.mp4"
    v.touch()
    res = tool.execute({"video_path": str(v)})
    assert not res.success
    assert "Missing caption" in res.error


def test_scheduled_time_validation(tmp_path: Path):
    v = tmp_path / "test.mp4"
    v.write_bytes(b"dummy mp4 content")

    tool = FacebookPublisher()

    # Too soon (< 10 minutes)
    res = tool.execute({
        "video_path": str(v),
        "caption": "Tin tức",
        "scheduled_publish_time": int(time.time()) + 300,
    })
    assert not res.success
    assert "must be between 10m and 75d" in res.error

    # Too far (> 75 days)
    res2 = tool.execute({
        "video_path": str(v),
        "caption": "Tin tức",
        "scheduled_publish_time": int(time.time()) + 7000000,
    })
    assert not res2.success
    assert "must be between 10m and 75d" in res2.error

    # Invalid type
    res3 = tool.execute({
        "video_path": str(v),
        "caption": "Tin tức",
        "scheduled_publish_time": "invalid_epoch",
    })
    assert not res3.success
    assert "Invalid scheduled_publish_time" in res3.error


def test_check_readiness_and_scopes():
    mock_session = MagicMock()
    mock_status_resp = MagicMock()
    mock_status_resp.status_code = 200
    mock_status_resp.json.return_value = {
        "module": "facebook-suite",
        "status": "enabled",
        "user_id": "1000888",
    }
    mock_scopes_resp = MagicMock()
    mock_scopes_resp.status_code = 200
    mock_scopes_resp.json.return_value = {
        "data": [{"id": "1435449429646177", "name": "AI Daily News"}],
    }

    def mock_get(url, **kwargs):
        if "status" in url:
            return mock_status_resp
        if "scopes" in url:
            return mock_scopes_resp
        return MagicMock(status_code=404)

    mock_session.get.side_effect = mock_get
    tool = FacebookPublisher(http_session=mock_session)

    status = tool.check_readiness()
    assert status.get("status") == "enabled"
    assert status.get("user_id") == "1000888"

    scopes = tool.get_scopes()
    assert "data" in scopes
    assert scopes["data"][0]["name"] == "AI Daily News"


def test_import_har_and_get_config(tmp_path: Path):
    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "status": "ok",
        "message": "HAR credentials extracted and saved.",
    }
    mock_session.post.return_value = mock_post_resp

    mock_cfg_resp = MagicMock()
    mock_cfg_resp.status_code = 200
    mock_cfg_resp.json.return_value = {"status": "ok", "actor_id": "1435449429646177"}
    mock_session.get.return_value = mock_cfg_resp

    tool = FacebookPublisher(http_session=mock_session)

    har_file = tmp_path / "download-facebook.har"
    har_file.write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")

    res = tool.import_har(har_file)
    assert res.get("status") == "ok"

    cfg = tool.get_config()
    assert cfg.get("actor_id") == "1435449429646177"


def test_publish_status():
    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"status": "success", "post_id": "post_789"}
    mock_session.post.return_value = mock_post_resp

    tool = FacebookPublisher(http_session=mock_session)
    res = tool.publish_status("Hello world from automated publishing!", target_id="1435449429646177")
    assert res.get("status") == "success"
    assert res.get("post_id") == "post_789"


def test_scheduled_publish_happy_path(tmp_path: Path):
    v = tmp_path / "facebook_reel.mp4"
    v.write_bytes(b"sample video bytes")

    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "status": "success",
        "video_id": "1089594350750481",
        "target_id": "1435449429646177",
        "publish_result": {"id": "1089594350750481"},
    }
    mock_session.post.return_value = mock_post_resp

    tool = FacebookPublisher(http_session=mock_session)
    sched_time = int(time.time()) + 7200  # 2 hours in advance

    result = tool.execute({
        "video_path": str(v),
        "title": "Bản tin AI hôm nay",
        "caption": "Chi tiết về mô hình AI mới #tech #news",
        "target_id": "1435449429646177",
        "scheduled_publish_time": sched_time,
        "publish_type": "REEL",
        "enable_auto_translate": True,
    })

    assert result.success
    assert result.data["status"] == "scheduled"
    assert result.data["video_id"] == "1089594350750481"
    assert result.data["scheduled_publish_time"] == sched_time
    assert result.data["auto_translate_enabled"] is True
    assert result.data["publish_type"] == "REEL"
    assert "1089594350750481" in result.data["video_url"]

    # Check payload sent to gateway
    post_args = mock_session.post.call_args
    sent_payload = post_args[1]["json"]
    assert sent_payload["target_id"] == "1435449429646177"
    assert sent_payload["scheduled_publish_time"] == sched_time
    assert sent_payload["enable_auto_translate"] is True
    assert sent_payload["translated_languages"] == DEFAULT_14_LANGUAGES
    assert sent_payload["file_name"] == "facebook_reel.mp4"
    assert sent_payload["publish_type"] == "REEL"
    assert "video_base64" in sent_payload


def test_endpoint_fallback_on_404(tmp_path: Path):
    v = tmp_path / "vid.mp4"
    v.write_bytes(b"content")

    mock_session = MagicMock()

    resp_404 = MagicMock()
    resp_404.status_code = 404

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "status": "success",
        "video_id": "video_999",
        "target_id": "page_123",
    }

    def mock_post(url, **kwargs):
        if url.endswith("/upload/video"):
            return resp_404
        if url.endswith("/publish"):
            return resp_200
        return resp_404

    mock_session.post.side_effect = mock_post
    tool = FacebookPublisher(http_session=mock_session)

    res = tool.execute({
        "video_path": str(v),
        "caption": "Hello world",
    })

    assert res.success
    assert res.data["video_id"] == "video_999"


def test_error_response_handling(tmp_path: Path):
    v = tmp_path / "vid.mp4"
    v.write_bytes(b"content")

    mock_session = MagicMock()
    resp_err = MagicMock()
    resp_err.status_code = 200
    resp_err.json.return_value = {
        "error": {"code": 400, "message": "Missing actor_id session credential"}
    }
    mock_session.post.return_value = resp_err

    tool = FacebookPublisher(http_session=mock_session)
    res = tool.execute({
        "video_path": str(v),
        "caption": "Test error",
    })

    assert not res.success
    assert "Missing actor_id" in res.error
