"""Unit tests to boost coverage on tools.publish_store."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_failed_claim_recovery_uses_version_precondition():
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {"fields": {"status": {"stringValue": "failed"}}, "updateTime": "2026-11-05T00:00:00Z"}
    store.session.get.return_value = snapshot
    store.session.patch.return_value = MagicMock(status_code=412)
    claimed, _ = store.reclaim_failed("key", {"status": "scheduling"})
    assert not claimed
    params = store.session.patch.call_args.kwargs["params"]
    assert ("currentDocument.updateTime", "2026-11-05T00:00:00Z") in params


def test_failed_claim_with_remote_id_is_never_reclaimed():
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {"fields": {"status": {"stringValue": "failed"}, "video_id": {"stringValue": "remote"}}, "updateTime": "2026-11-05T00:00:00Z"}
    store.session.get.return_value = snapshot
    claimed, _ = store.reclaim_failed("key", {"status": "scheduling"})
    assert not claimed
    store.session.patch.assert_not_called()


def test_failed_claim_recovery_updates_slot_and_clears_failure_fields():
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {"fields": {"status": {"stringValue": "failed"}}, "updateTime": "2026-11-05T00:00:00Z"}
    store.session.get.return_value = snapshot
    store.session.patch.return_value = MagicMock(status_code=200)
    claimed, _ = store.reclaim_failed("key", {"status": "scheduling", "scheduled_for": "2099-01-01T09:00:00+00:00"})
    assert claimed
    kwargs = store.session.patch.call_args.kwargs
    assert kwargs["json"]["fields"]["scheduled_for"] == {"stringValue": "2099-01-01T09:00:00+00:00"}
    assert ("updateMask.fieldPaths", "error") in kwargs["params"]
    assert ("updateMask.fieldPaths", "failed_at") in kwargs["params"]
    assert "error" not in kwargs["json"]["fields"]
    assert "failed_at" not in kwargs["json"]["fields"]


@pytest.mark.parametrize("field", ["title", "source_topic", "asset_path"])
def test_failed_claim_does_not_reuse_changed_uniqueness_identity(field):
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {"fields": {"status": {"stringValue": "failed"}, field: {"stringValue": "old"}}, "updateTime": "2026-11-05T00:00:00Z"}
    store.session.get.return_value = snapshot
    store.session.patch.return_value = MagicMock(status_code=200)
    claimed, _ = store.reclaim_failed("key", {"status": "scheduling", field: "new"})
    assert not claimed
    store.session.patch.assert_not_called()


def test_competing_failed_claim_retries_only_one_succeeds():
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    class VersionedSession:
        version = "v1"

        def get(self, *args, **kwargs):
            snapshot = MagicMock(status_code=200)
            snapshot.json.return_value = {"fields": {"status": {"stringValue": "failed"}}, "updateTime": "v1"}
            barrier.wait(timeout=5)
            return snapshot

        def patch(self, *args, **kwargs):
            expected = dict(kwargs["params"])["currentDocument.updateTime"]
            with lock:
                if self.version != expected:
                    return MagicMock(status_code=412)
                self.version = "v2"
                return MagicMock(status_code=200)

    store.session = VersionedSession()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: store.reclaim_failed("key", {"status": "scheduling"})[0], range(2)))
    assert sorted(results) == [False, True]


def test_instagram_reservation_claim_uses_document_version():
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {
        "fields": {"status": {"stringValue": "scheduling"}, "platform": {"stringValue": "instagram"}},
        "updateTime": "2026-11-05T00:00:00Z",
    }
    store.session.get.return_value = snapshot
    store.session.patch.return_value = MagicMock(status_code=412)
    claimed, _ = store.claim_instagram_reservation("key")
    assert not claimed
    assert ("currentDocument.updateTime", "2026-11-05T00:00:00Z") in store.session.patch.call_args.kwargs["params"]


@pytest.mark.parametrize("method,status,platform", [("reclaim_failed", "failed", "youtube"), ("claim_instagram_reservation", "scheduling", "instagram")])
def test_firestore_failed_precondition_is_lost_claim(method, status, platform):
    store = publish_store.PublishStore.__new__(publish_store.PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/publishes"
    store.session = MagicMock()
    snapshot = MagicMock(status_code=200)
    snapshot.json.return_value = {"fields": {"status": {"stringValue": status}, "platform": {"stringValue": platform}}, "updateTime": "2026-11-05T00:00:00Z"}
    store.session.get.return_value = snapshot
    conflict = MagicMock(status_code=400)
    conflict.json.return_value = {"error": {"status": "FAILED_PRECONDITION"}}
    store.session.patch.return_value = conflict
    claimed, _ = getattr(store, method)("key", {"status": "scheduling"}) if method == "reclaim_failed" else getattr(store, method)("key")
    assert not claimed
