"""Unit tests for scripts/attach_youtube_thumbnail.py."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.attach_youtube_thumbnail import (
    attach_thumbnail_to_video,
    resolve_video_id,
)


def test_resolve_video_id_explicit():
    res = resolve_video_id(Path("/tmp"), explicit_video_id="test123abc")
    assert res == "test123abc"


def test_resolve_video_id_from_publish_log(tmp_path):
    pdir = tmp_path / "cand_test"
    pdir.mkdir()
    log_file = pdir / "publish_log.json"
    log_file.write_text(json.dumps({
        "entries": [
            {"platform": "instagram", "video_id": "ig_123"},
            {"platform": "youtube", "video_id": "yt_xyz_789"},
        ]
    }))

    res = resolve_video_id(pdir)
    assert res == "yt_xyz_789"


def test_attach_thumbnail_missing_project():
    success, status, err = attach_thumbnail_to_video(Path("/nonexistent/path"))
    assert not success
    assert status == "PROJECT_NOT_FOUND"


def test_attach_thumbnail_missing_video_id(tmp_path):
    pdir = tmp_path / "cand_empty"
    pdir.mkdir()
    success, status, err = attach_thumbnail_to_video(pdir)
    assert not success
    assert status == "MISSING_VIDEO_ID"


@patch("scripts.attach_youtube_thumbnail.YoutubePublisher")
@patch("scripts.attach_youtube_thumbnail._upload_thumbnail_if_present")
def test_attach_thumbnail_success(mock_upload, mock_publisher_cls, tmp_path):
    pdir = tmp_path / "cand_success"
    pdir.mkdir()
    thumb_dir = pdir / "thumbnails"
    thumb_dir.mkdir()
    thumb_file = thumb_dir / "thumbnail.png"
    thumb_file.write_text("fake image content")

    mock_service = MagicMock()
    mock_pub = MagicMock()
    mock_pub._get_authenticated_service.return_value = mock_service
    mock_publisher_cls.return_value = mock_pub

    mock_upload.return_value = ("THUMBNAIL_ATTACHED", None)

    success, status, err = attach_thumbnail_to_video(
        project_dir=pdir,
        video_id="vid_test_123",
        thumbnail_path=str(thumb_file),
    )

    assert success is True
    assert status == "THUMBNAIL_ATTACHED"
    assert err is None
    mock_upload.assert_called_once_with(mock_service, "vid_test_123", str(thumb_file))


@patch("scripts.attach_youtube_thumbnail.YoutubePublisher")
@patch("scripts.attach_youtube_thumbnail._upload_thumbnail_if_present")
def test_attach_all_thumbnails(mock_upload, mock_publisher_cls, tmp_path):
    from scripts.attach_youtube_thumbnail import attach_all_thumbnails

    cand_dir = tmp_path / "cand_0e4153ec05bae47d"
    cand_dir.mkdir()
    thumb_dir = cand_dir / "thumbnails"
    thumb_dir.mkdir()
    thumb_file = thumb_dir / "thumbnail.png"
    # Create file > 50_000 bytes
    thumb_file.write_bytes(b"x" * 60_000)

    mock_service = MagicMock()
    mock_pub = MagicMock()
    mock_pub._get_authenticated_service.return_value = mock_service
    mock_publisher_cls.return_value = mock_pub
    mock_upload.return_value = ("THUMBNAIL_ATTACHED", None)

    summary = attach_all_thumbnails(projects_dir=tmp_path, force_regenerate=False)
    assert summary["total"] == 1
    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert summary["results"]["cand_0e4153ec05bae47d"]["video_id"] == "vv8kAc3kcew"

