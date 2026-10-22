"""Comprehensive unit tests for youtube_publisher helper functions and error handling."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.publishers.youtube_publisher import (
    YoutubePublisher,
    _check_oembed_fallback,
    _check_text_prose,
    _check_video_geometry,
    _classify_check_error,
    _construct_upload_body,
    _resolve_check_credentials,
    _upload_thumbnail_if_present,
    _verify_authenticated_channel,
    _verify_channel_guard_requirements,
)


def test_check_video_geometry_vertical_and_horizontal(tmp_path, monkeypatch):
    p = tmp_path / "test.mp4"
    p.write_bytes(b"dummy")

    with patch("tools.publishers.platform_routes.ensure_vertical") as mock_v, \
         patch("tools.publishers.platform_routes.ensure_youtube_short") as mock_s:
        res = _check_video_geometry(p, "short")
        assert res is None
        mock_v.assert_called_once_with(p)
        mock_s.assert_called_once_with(p)

    with patch("tools.publishers.platform_routes.ensure_horizontal") as mock_h:
        res = _check_video_geometry(p, "longform")
        assert res is None
        mock_h.assert_called_once_with(p)

    with patch("tools.publishers.platform_routes.ensure_vertical", side_effect=ValueError("Must be vertical")):
        res = _check_video_geometry(p, "short")
        assert res is not None
        assert not res.success
        assert "Must be vertical" in res.error


def test_check_text_prose_english():
    # Valid English
    res = _check_text_prose("Breaking tech news today", "This is an informative update about AI.", "en-US")
    assert res is None

    # Invalid English with Vietnamese diacritics
    res = _check_text_prose("Tin tức công nghệ", "Detailed description", "en-US")
    assert res is not None
    assert not res.success
    assert "Invalid YouTube title" in res.error


def test_check_text_prose_vietnamese():
    # Valid Vietnamese
    res = _check_text_prose("Chiều tin công nghệ trí tuệ nhân tạo", "Bản tin tổng hợp chi tiết chiều nay.", "vi")
    assert res is None

    # Invalid Vietnamese prose (only English words)
    res = _check_text_prose("Breaking news today", "Description here", "vi")
    assert res is not None
    assert not res.success
    assert "Invalid YouTube title" in res.error


def test_verify_channel_guard_requirements(monkeypatch):
    # US upload without channel ID -> fails
    res = _verify_channel_guard_requirements(None, is_us_upload=True)
    assert res is not None
    assert not res.success
    assert "expected_channel_id is not specified" in res.error

    # Guard required via env without channel ID -> fails
    monkeypatch.setenv("CHANNEL_GUARD_REQUIRED", "1")
    res = _verify_channel_guard_requirements(None, is_us_upload=False)
    assert res is not None
    assert not res.success

    # With channel ID -> passes
    res = _verify_channel_guard_requirements("UC12345", is_us_upload=True)
    assert res is None


def test_verify_authenticated_channel():
    mock_youtube = MagicMock()
    mock_req = MagicMock()
    mock_youtube.channels().list.return_value = mock_req

    # Match
    mock_req.execute.return_value = {"items": [{"id": "UC12345"}]}
    res = _verify_authenticated_channel(mock_youtube, "UC12345")
    assert res is None

    # Mismatch
    mock_req.execute.return_value = {"items": [{"id": "UC_OTHER"}]}
    res = _verify_authenticated_channel(mock_youtube, "UC12345")
    assert res is not None
    assert not res.success
    assert "does not match" in res.error

    # No channel items
    mock_req.execute.return_value = {"items": []}
    res = _verify_authenticated_channel(mock_youtube, "UC12345")
    assert res is not None
    assert not res.success
    assert "No channel found" in res.error


def test_construct_upload_body():
    body_en = _construct_upload_body(
        inputs={"made_for_kids": True, "contains_synthetic_media": True},
        title="AI News",
        description="Today's update",
        tags=["tech", "ai"],
        category_id="28",
        privacy_status="unlisted",
        publish_at="2026-10-25T10:00:00Z",
        locale="en-US",
    )
    assert body_en["snippet"]["defaultLanguage"] == "en-US"
    assert body_en["snippet"]["defaultAudioLanguage"] == "en-US"
    assert body_en["status"]["selfDeclaredMadeForKids"] is True
    assert body_en["status"]["containsSyntheticMedia"] is True
    assert body_en["status"]["publishAt"] == "2026-10-25T10:00:00Z"
    assert body_en["status"]["privacyStatus"] == "unlisted"

    body_vi = _construct_upload_body(
        inputs={},
        title="Tin tức",
        description="Chi tiết",
        tags=[],
        category_id="25",
        privacy_status="public",
        publish_at=None,
        locale="vi-VN",
    )
    assert body_vi["snippet"]["defaultLanguage"] == "vi-VN"
    assert body_vi["snippet"]["defaultAudioLanguage"] == "vi-VN"


def test_upload_thumbnail_if_present(tmp_path):
    mock_youtube = MagicMock()
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff")

    with patch("googleapiclient.http.MediaFileUpload") as mock_media:
        mock_upload_req = MagicMock()
        mock_youtube.thumbnails().set.return_value = mock_upload_req
        _upload_thumbnail_if_present(mock_youtube, "vid123", str(thumb))
        mock_upload_req.execute.assert_called_once()

    # When thumb doesn't exist, does not raise
    _upload_thumbnail_if_present(mock_youtube, "vid123", str(tmp_path / "nonexistent.jpg"))
    # When thumb is None, does not raise
    _upload_thumbnail_if_present(mock_youtube, "vid123", None)


def test_resolve_check_credentials(tmp_path, monkeypatch):
    # Missing secret file env
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRET_FILE", raising=False)
    res = _resolve_check_credentials()
    assert isinstance(res, dict)
    assert res["status"] == "unavailable"
    assert res["error_type"] == "missing_config"

    # Files do not exist on disk
    secret = tmp_path / "secret.json"
    token = tmp_path / "token.json"
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token))
    res = _resolve_check_credentials()
    assert isinstance(res, dict)
    assert res["error_type"] == "missing_credentials"

    # Files exist on disk
    secret.write_text("{}")
    token.write_text("{}")
    res = _resolve_check_credentials()
    assert isinstance(res, tuple)
    assert res[0] == secret
    assert res[1] == token


def test_check_oembed_fallback():
    # Invalid video ID format
    assert _check_oembed_fallback("invalid;id?") is None

    # Valid video ID, successful oembed
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"title": "Sample Title", "author_name": "Author"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        data = _check_oembed_fallback("valid_video_id_123")
        assert data is not None
        assert data["status"] == "unverified_oembed"
        assert data["title"] == "Sample Title"
        assert data["via_oembed"] is True

    # HTTP error fallback returns None
    with patch("urllib.request.urlopen", side_effect=Exception("network down")):
        assert _check_oembed_fallback("valid_video_id_123") is None


def test_classify_check_error():
    exc = Exception("AUTH_REQUIRED: please login")
    data = _classify_check_error(exc)
    assert data["status"] == "error"
    assert data["error_type"] == "auth_required"

    class MockHttpError(Exception):
        status_code = 404

    http_exc = MockHttpError("Resource not found")
    data_http = _classify_check_error(http_exc)
    assert data_http["error_type"] == "http_error"
    assert data_http["status_code"] == 404
