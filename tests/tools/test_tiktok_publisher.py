"""Unit tests for TiktokPublisher via Toolcase Gateway Adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.publishers.tiktok_publisher import TiktokPublisher
from tools.tool_registry import ToolRegistry


def test_tiktok_publisher_discovered_in_registry():
    """Verify ToolRegistry discovers tiktok_publisher automatically."""
    registry = ToolRegistry()
    registry.discover()
    assert "tiktok_publisher" in registry._tools
    tool_cls = registry._tools["tiktok_publisher"]
    assert tool_cls.capability == "publish"
    assert tool_cls.provider == "tiktok"


def test_gateway_url_resolution(monkeypatch):
    """Test resolution of Toolcase Gateway URLs."""
    tool = TiktokPublisher()

    # Default fallback
    monkeypatch.delenv("TIKTOK_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TIKTOK_API_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLCASE_GATEWAY_URL", raising=False)
    assert tool.get_gateway_base_url() == "http://127.0.0.1:20129/tiktok"

    # From TOOLCASE_GATEWAY_URL
    monkeypatch.setenv("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129")
    assert tool.get_gateway_base_url() == "http://127.0.0.1:20129/tiktok"

    # From TIKTOK_GATEWAY_BASE_URL
    monkeypatch.setenv("TIKTOK_GATEWAY_BASE_URL", "http://localhost:20129/custom/tiktok")
    assert tool.get_gateway_base_url() == "http://localhost:20129/custom/tiktok"

    # Override in inputs
    assert tool.get_gateway_base_url({"gateway_url": "http://10.0.0.1:20129/tiktok"}) == "http://10.0.0.1:20129/tiktok"


def test_missing_and_invalid_inputs(tmp_path: Path):
    tool = TiktokPublisher()

    # Missing video_path
    res = tool.execute({})
    assert not res.success
    assert "video_path" in res.error

    # Non-existent file
    res = tool.execute({"video_path": str(tmp_path / "nonexistent.mp4"), "caption": "Tin tức"})
    assert not res.success
    assert "not found" in res.error

    # Missing caption/title
    v = tmp_path / "vid.mp4"
    v.touch()
    res = tool.execute({"video_path": str(v)})
    assert not res.success
    assert "Missing caption" in res.error


def test_cookie_normalization():
    tool = TiktokPublisher()
    raw = [
        {"name": "sessionid", "value": "sess123"},
        {"name": "tt_csrf_token", "value": "csrfABC"},
        {"name": "store-idc", "value": "alisg"},
    ]
    cookie_str, csrf = tool._normalize_cookie_list_to_header(raw)
    assert "sessionid=sess123" in cookie_str
    assert "store-idc=alisg" in cookie_str
    assert csrf == "csrfABC"


def test_check_readiness():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "module": "tiktok-studio",
        "status": "enabled",
        "configured": True,
        "has_cookie": True,
        "has_csrf_token": True,
    }
    mock_session.get.return_value = mock_resp

    tool = TiktokPublisher(http_session=mock_session)
    status = tool.check_readiness("http://127.0.0.1:20130/tiktok")
    assert status["status"] == "enabled"
    assert status["configured"] is True


def test_check_video_published_found():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status_code": 0,
        "items": [
            {
                "id": "7702355712046828820",
                "desc": "AI video #ai",
                "stats": {"play_count": 150, "like_count": 25},
            }
        ],
    }
    mock_session.get.return_value = mock_resp

    tool = TiktokPublisher(http_session=mock_session)
    result = tool.check_video_published("7702355712046828820")
    assert result["status"] == "published"
    assert result["play_count"] == 150


def test_check_video_published_not_found():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status_code": 0, "items": []}
    mock_session.get.return_value = mock_resp

    tool = TiktokPublisher(http_session=mock_session)
    result = tool.check_video_published("99999999999")
    assert result["status"] == "not_found"


def test_publish_happy_path(tmp_path: Path):
    v = tmp_path / "valid_vertical.mp4"
    v.touch()

    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "project_id": "7702355712046828820",
        "item_id": "7702355712046828820",
        "project_status": 1,
        "visibility_type": 1,
        "visibility": "only-me",
        "status_code": 0,
    }
    mock_session.post.return_value = mock_post_resp

    tool = TiktokPublisher(http_session=mock_session)

    with patch("tools.publishers.platform_routes.ensure_vertical"):
        result = tool.execute({
            "video_path": str(v),
            "caption": "Video công nghệ mới #congnghe #ai",
            "title": "Công nghệ AI mới",
            "visibility": "only-me",
        })

    assert result.success
    assert result.data["status"] == "published"
    assert result.data["project_id"] == "7702355712046828820"
    assert result.data["visibility"] == "only-me"
    assert "publish_log" in result.data


def test_publish_handles_auth_error(tmp_path: Path):
    v = tmp_path / "vid.mp4"
    v.touch()

    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 401
    mock_post_resp.text = "Unauthorized: session expired"
    mock_session.post.return_value = mock_post_resp

    tool = TiktokPublisher(http_session=mock_session)

    with patch("tools.publishers.platform_routes.ensure_vertical"):
        result = tool.execute({
            "video_path": str(v),
            "caption": "Video công nghệ #ai",
        })

    assert not result.success
    assert "401" in result.error
    assert "session expired" in result.error.lower()


def test_publish_scheduled_happy_path(tmp_path: Path):
    import time
    v = tmp_path / "valid_vertical.mp4"
    v.touch()

    mock_session = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    sched_epoch = int(time.time()) + 3600  # 1 hour in future
    mock_post_resp.json.return_value = {
        "project_id": "7702471269211444231",
        "item_id": "7702471269211444231",
        "status": "scheduled",
        "schedule_time": sched_epoch,
        "status_code": 0,
    }
    mock_session.post.return_value = mock_post_resp

    tool = TiktokPublisher(http_session=mock_session)
    with patch("tools.publishers.platform_routes.ensure_vertical"):
        result = tool.execute({
            "video_path": str(v),
            "caption": "Video lịch trình sáng mai #schedule #ai",
            "schedule_time": sched_epoch,
        })

    assert result.success
    assert result.data["status"] == "scheduled"
    assert result.data["schedule_time"] == sched_epoch
    assert result.data["visibility"] == "public"  # Defaulted to public for scheduled
    sent_payload = mock_session.post.call_args[1]["json"]
    assert sent_payload["schedule_time"] == sched_epoch
    assert sent_payload["visibility"] == "public"


def test_publish_scheduled_validation_errors(tmp_path: Path):
    import time
    v = tmp_path / "valid_vertical.mp4"
    v.touch()

    tool = TiktokPublisher()
    with patch("tools.publishers.platform_routes.ensure_vertical"):
        # Too soon (< 15 min)
        res = tool.execute({
            "video_path": str(v),
            "caption": "Video kiểm thử #test",
            "schedule_time": int(time.time()) + 300,
        })
        assert not res.success
        assert "must be between 15m and 10d" in res.error

        # Too far (> 10 days)
        res2 = tool.execute({
            "video_path": str(v),
            "caption": "Video kiểm thử #test",
            "schedule_time": int(time.time()) + 1000000,
        })
        assert not res2.success
        assert "must be between 15m and 10d" in res2.error

        # Invalid type
        res3 = tool.execute({
            "video_path": str(v),
            "caption": "Video kiểm thử #test",
            "schedule_time": "invalid_epoch",
        })
        assert not res3.success
        assert "Invalid schedule_time" in res3.error

