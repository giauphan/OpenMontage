from pathlib import Path
from unittest.mock import MagicMock

from scripts.facebook_native import publish_facebook_native


class FakeStore:
    def __init__(self, existing=None, claimed=True):
        self.existing = existing
        self.claimed = claimed
        self.published = []
        self.scheduled = []
        self.failed = []
        self.claims = []

    def get(self, key):
        return self.existing

    def claim(self, **kwargs):
        self.claims.append(kwargs)
        return "fb_key", self.claimed, {}

    def mark_scheduled(self, key, **kwargs):
        self.scheduled.append((key, kwargs))

    def mark_published(self, key, **kwargs):
        self.published.append((key, kwargs))

    def mark_failed(self, key, error):
        self.failed.append((key, error))


def _call(store, asset: Path, **overrides):
    kwargs = dict(
        date="2099-01-01",
        topic_id="cand_x",
        asset_path=asset,
        title="Title",
        description="Desc",
        scheduled_for="2099-01-01T09:15:00+00:00",
        content_hash=None,
        template_id=None,
        dry_run=False,
    )
    kwargs.update(overrides)
    return publish_facebook_native(store, **kwargs)


def _publisher(success=True, data=None, error=None):
    pub = MagicMock()
    pub.execute.return_value = MagicMock(success=success, data=data or {}, error=error)
    return MagicMock(return_value=pub), pub


def test_missing_asset_returns_failure(tmp_path):
    store = FakeStore()
    factory, _ = _publisher()
    assert _call(store, tmp_path / "missing.mp4", publisher_factory=factory) is True
    assert store.claims == []


def test_dry_run_skips_side_effects(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, pub = _publisher()
    assert _call(store, asset, dry_run=True, publisher_factory=factory) is False
    assert store.claims == []
    assert pub.execute.called is False


def test_existing_published_record_skips(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore(existing={"status": "published", "video_url": "https://facebook.com/123"})
    factory, pub = _publisher()
    assert _call(store, asset, publisher_factory=factory) is False
    assert store.claims == []
    assert pub.execute.called is False


def test_failed_record_with_remote_id_requires_reconciliation(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore(existing={"status": "failed", "platform_id": "remote-123"})
    factory, pub = _publisher(data={"facebook_post_id": "new-id"})
    assert _call(store, asset, publisher_factory=factory) is True
    assert not store.claims and not pub.execute.called


def test_failed_claim_not_owned_does_not_retry_upload(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore(existing={"status": "failed"}, claimed=False)
    factory, pub = _publisher(data={"facebook_post_id": "new-id"})
    assert _call(store, asset, publisher_factory=factory) is True
    assert len(store.claims) == 1 and not pub.execute.called


def test_schedules_and_records_remote_id(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, pub = _publisher(data={
        "facebook_post_id": "1089594350750481",
        "video_id": "1089594350750481",
        "video_url": "https://facebook.com/1435449429646177/videos/1089594350750481",
        "status": "scheduled",
    })
    assert _call(store, asset, publisher_factory=factory, target_id="1435449429646177") is False
    assert pub.execute.call_args.args[0]["video_path"] == str(asset)
    assert pub.execute.call_args.args[0]["target_id"] == "1435449429646177"
    assert pub.execute.call_args.args[0]["scheduled_publish_time"] > 0
    assert pub.execute.call_args.args[0]["enable_auto_translate"] is True
    assert store.scheduled[0][1]["video_id"] == "1089594350750481"
    assert store.claims[0]["platform"] == "facebook"


def test_failure_marks_failed_and_reports(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, _ = _publisher(success=False, error="Upload session rejected")
    assert _call(store, asset, publisher_factory=factory) is True
    assert store.failed[0][1] == "Upload session rejected"
