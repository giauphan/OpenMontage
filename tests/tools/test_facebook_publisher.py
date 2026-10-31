"""Unit tests for FacebookPublisher via Toolcase Gateway Adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.publishers.facebook_publisher import FacebookPublisher, DEFAULT_14_LANGUAGES
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
        "enable_auto_translate": True,
    })

    assert result.success
    assert result.data["status"] == "scheduled"
    assert result.data["video_id"] == "1089594350750481"
    assert result.data["scheduled_publish_time"] == sched_time
    assert result.data["auto_translate_enabled"] is True
    assert "1089594350750481" in result.data["video_url"]

    # Check payload sent to gateway
    post_args = mock_session.post.call_args
    sent_payload = post_args[1]["json"]
    assert sent_payload["target_id"] == "1435449429646177"
    assert sent_payload["scheduled_publish_time"] == sched_time
    assert sent_payload["enable_auto_translate"] is True
    assert sent_payload["translated_languages"] == DEFAULT_14_LANGUAGES
    assert sent_payload["file_name"] == "facebook_reel.mp4"
    assert "video_base64" in sent_payload
