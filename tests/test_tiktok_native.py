from pathlib import Path
from unittest.mock import MagicMock

from scripts.tiktok_native import publish_tiktok_native, tiktok_visibility


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
        return "tt_key", self.claimed, {}

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
    return publish_tiktok_native(store, **kwargs)


def _publisher(success=True, data=None, error=None):
    pub = MagicMock()
    pub.execute.return_value = MagicMock(success=success, data=data or {}, error=error)
    return MagicMock(return_value=pub), pub


def test_visibility_fails_closed_to_private(monkeypatch):
    monkeypatch.setenv("TIKTOK_DEFAULT_VISIBILITY", "everyone")
    assert tiktok_visibility() == "only-me"
    monkeypatch.setenv("TIKTOK_DEFAULT_VISIBILITY", "Public")
    assert tiktok_visibility() == "public"


def test_schedules_and_records_remote_id(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, pub = _publisher(data={"item_id": "123", "project_id": "p1", "video_url": "u", "status": "scheduled"})
    assert _call(store, asset, publisher_factory=factory) is False
    assert pub.execute.call_args.args[0]["video_path"] == str(asset)
    assert pub.execute.call_args.args[0]["schedule_time"] > 0
    assert store.scheduled[0][1]["video_id"] == "123"
    assert store.claims[0]["platform"] == "tiktok"


def test_immediate_publishes_when_no_schedule(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, pub = _publisher(data={"item_id": "123", "project_id": "p1", "video_url": "u", "status": "published"})
    assert _call(store, asset, scheduled_for="", publisher_factory=factory) is False
    assert "schedule_time" not in pub.execute.call_args.args[0]
    assert store.published[0][1]["video_id"] == "123"


def test_failure_marks_failed_and_reports(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, _ = _publisher(success=False, error="session expired")
    assert _call(store, asset, publisher_factory=factory) is True
    assert store.failed and not store.published


def test_success_without_remote_id_is_failure(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, _ = _publisher(success=True, data={})
    assert _call(store, asset, publisher_factory=factory) is True
    assert store.failed


def test_existing_published_record_is_not_republished(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore(existing={"status": "published", "video_url": "u"})
    factory, pub = _publisher()
    assert _call(store, asset, publisher_factory=factory) is False
    assert pub.execute.call_count == 0 and not store.claims


def test_unclaimed_duplicate_is_skipped(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore(claimed=False)
    factory, pub = _publisher()
    assert _call(store, asset, publisher_factory=factory) is False
    assert pub.execute.call_count == 0


def test_dry_run_never_touches_store_or_network(tmp_path):
    asset = tmp_path / "v.mp4"
    asset.touch()
    store = FakeStore()
    factory, pub = _publisher()
    assert _call(store, asset, dry_run=True, publisher_factory=factory) is False
    assert not store.claims and pub.execute.call_count == 0


def test_missing_asset_fails_closed(tmp_path):
    store = FakeStore()
    assert _call(store, tmp_path / "missing.mp4") is True
    assert not store.claims
