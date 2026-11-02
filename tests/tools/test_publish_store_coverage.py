"""Unit tests to boost coverage on tools.publish_store."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tools import publish_store


def test_media_fingerprint(tmp_path: Path):
    sample = tmp_path / "video.mp4"
    sample.write_bytes(b"DUMMY_VIDEO")
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout=b"FINGERPRINT_BYTES")
        fp = publish_store.media_fingerprint(sample)
        assert len(fp) == 64


def test_existing_record_summary():
    assert publish_store.existing_record_summary(None) == "missing"
    assert publish_store.existing_record_summary({}) == "missing"
    assert publish_store.existing_record_summary({"status": "published", "video_url": "https://fb.com/v1"}) == "published https://fb.com/v1"
    assert publish_store.existing_record_summary({"status": "pending", "video_id": "vid_123"}) == "pending vid_123"


def test_env_value_and_service_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TEST_KEY", raising=False)
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", "test_env_sa")
    assert publish_store._env_value("FIREBASE_SERVICE_ACCOUNT") == "test_env_sa"

    # _load_service_account missing
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT", raising=False)
    with pytest.raises(RuntimeError, match="FIREBASE_SERVICE_ACCOUNT is missing"):
        publish_store._load_service_account()

    # file:// path
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps({"project_id": "test-p"}))
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", f"file://{sa_file}")
    assert publish_store._load_service_account() == {"project_id": "test-p"}


def test_create_many_once_and_error_handling():
    mock_session = MagicMock()
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.session = mock_session
    store.base_url = "https://firestore.googleapis.com/v1/projects/test-p/databases/(default)/documents/publishes"
    store.commit_url = "https://firestore.googleapis.com/v1/projects/test-p/databases/(default)/documents:commit"

    # create_many_once success
    mock_session.post.return_value = MagicMock(status_code=200)
    assert store.create_many_once({"k1": {"val": 1}}) is True

    # create_many_once 409 conflict
    mock_session.post.return_value = MagicMock(status_code=409)
    assert store.create_many_once({"k1": {"val": 1}}) is False

    # _raise_for_error with json error
    err_resp = MagicMock(status_code=500)
    err_resp.json.return_value = {"error": {"message": "Internal firestore error"}}
    with pytest.raises(RuntimeError, match="Internal firestore error"):
        store._raise_for_error(err_resp)
