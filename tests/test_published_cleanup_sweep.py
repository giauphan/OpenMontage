"""Independent sweep regression tests: fake store/API and disposable media only."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import cleanup_published_projects as cleanup
from scripts import publish_active_projects as publisher
from tools.publish_store import file_sha256, publish_key
from tools.publishers.youtube_publisher import YoutubePublisher

DATE = "2020-01-01"
PID = "cand_sweep"


class FakeStore:
    def __init__(self, records):
        self.records = records

    def get(self, key):
        return self.records.get(key)

    def mark_published(self, key, **kwargs):
        self.records[key].update(status="published", **kwargs)
        return self.records[key]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    config = tmp_path / "config" / "publish_schedule.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"active_projects": [{"project_id": PID, "publish_date": DATE}]}))
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    monkeypatch.setattr(publisher, "CONFIG", config)
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "1")
    monkeypatch.setattr(cleanup, "PublishStore", Mock(side_effect=AssertionError("Real store forbidden")))
    return tmp_path, config


def project(root, location="projects", *, metadata=None, status="scheduled"):
    directory = root / location / PID
    renders = directory / "renders"
    renders.mkdir(parents=True)
    media = renders / "final_reels_vi_9x16.mp4"
    media.write_bytes(b"fixture media")
    full = renders / "final_full_vi_9x16.mp4"
    full.write_bytes(b"fixture full media")
    (directory / "publish_metadata.json").write_text(json.dumps(metadata or {}))
    records = {
        publish_key(DATE, PID, "youtube", "short"): {
            "platform": "youtube", "status": status,
            "scheduled_for": "2020-01-01T00:00:00Z", "video_id": "fake-video",
            "media_sha256": file_sha256(media),
        },
        publish_key(DATE, PID, "instagram", "reels"): {
            "platform": "instagram", "status": "published",
            "remote_status": {"status": "published"}, "media_sha256": file_sha256(media),
        },
    }
    records[publish_key(DATE, PID, "facebook", "reels")] = {
        "platform": "facebook", "status": "published",
        "remote_status": {"status": "published"}, "media_sha256": file_sha256(full),
    }
    return directory, FakeStore(records)


@pytest.mark.parametrize("location", ["projects", "projects_news", "projects/instagram"])
def test_active_scheduled_project_reconciles_and_cleans(sandbox, monkeypatch, location):
    root, config = sandbox
    directory, store = project(root, location)
    remote = Mock(return_value={"privacy_status": "public", "upload_status": "processed"})
    monkeypatch.setattr(YoutubePublisher, "check_video_published", remote)
    assert cleanup.sweep(apply=True, store=store) == 0
    remote.assert_called_once_with("fake-video")
    assert not directory.exists()
    assert json.loads(config.read_text())["active_projects"] == []
    audit = [json.loads(line) for line in (root / "logs/published_archive.jsonl").read_text().splitlines()]
    assert [entry["cleanup_state"] for entry in audit] == ["cleanup_pending", "cleanup_completed"]
    assert audit[0]["date"] == DATE
    assert audit[0]["media_hashes"]
    assert cleanup.sweep(apply=True, store=store) == 0
    remote.assert_called_once()


def test_inactive_metadata_date_is_used_without_schedule(sandbox, monkeypatch):
    root, config = sandbox
    config.unlink()
    directory, store = project(root, metadata={"publish_date": DATE})
    monkeypatch.setattr(YoutubePublisher, "check_video_published", Mock(return_value={
        "privacy_status": "public", "upload_status": "processed",
    }))
    assert cleanup.sweep(apply=True, store=store) == 0
    assert not directory.exists()


@pytest.mark.parametrize("response", [None, {"status": "error"}, {"privacy_status": "private", "upload_status": "processed"}, {"privacy_status": "public", "upload_status": "processed", "via_oembed": True}])
def test_unverified_remote_keeps_media_and_queue(sandbox, monkeypatch, response):
    root, config = sandbox
    directory, store = project(root)
    before = config.read_bytes()
    monkeypatch.setattr(YoutubePublisher, "check_video_published", Mock(return_value=response))
    assert cleanup.sweep(apply=True, store=store) == 0
    assert directory.exists() and config.read_bytes() == before
    assert not (root / "logs/published_archive.jsonl").exists()


@pytest.mark.parametrize("guard", ["failed", "missing_route", "hash", "duplicate", "identity", "audit", "future"])
def test_existing_safety_guards_remain_effective(sandbox, monkeypatch, guard):
    root, config = sandbox
    directory, store = project(root)
    youtube = store.get(publish_key(DATE, PID, "youtube", "short"))
    if guard == "failed":
        youtube["status"] = "failed"
    elif guard == "missing_route":
        store.records.pop(publish_key(DATE, PID, "instagram", "reels"))
    elif guard == "hash":
        youtube["media_sha256"] = "wrong"
    elif guard == "duplicate":
        (root / "projects_news" / PID).mkdir(parents=True)
    elif guard == "identity":
        (directory / "publish_metadata.json").write_text(json.dumps({"id": "different"}))
    elif guard == "audit":
        monkeypatch.setattr(publisher, "write_audit_tombstone", Mock(return_value=False))
    elif guard == "future":
        youtube["scheduled_for"] = "2999-01-01T00:00:00Z"
    remote = Mock(return_value={"privacy_status": "public", "upload_status": "processed"})
    monkeypatch.setattr(YoutubePublisher, "check_video_published", remote)
    before = config.read_bytes()
    assert cleanup.sweep(apply=True, store=store) == 0
    assert directory.exists() and config.read_bytes() == before
    if guard in ("failed", "future", "duplicate", "identity"):
        remote.assert_not_called()


def test_dry_run_is_read_only_and_does_not_reconcile(sandbox, monkeypatch):
    root, config = sandbox
    directory, store = project(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    remote = Mock(side_effect=AssertionError("Dry run must not call API"))
    monkeypatch.setattr(YoutubePublisher, "check_video_published", remote)
    assert cleanup.sweep(store=store) == 0
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    remote.assert_not_called()
    assert store.get(publish_key(DATE, PID, "youtube", "short"))["status"] == "scheduled"


@pytest.mark.parametrize("metadata", [{}, {"date": "invalid"}, {"date": "2020-01-02", "publish_date": DATE}, {"publish_date": []}])
def test_unresolvable_metadata_dates_are_retained(sandbox, metadata):
    root, config = sandbox
    config.write_text("{}")
    directory, store = project(root, metadata=metadata)
    assert list(cleanup.candidate_dates(root)) == []
    assert directory.exists()


def test_conflicting_queue_date_is_retained(sandbox):
    root, _ = sandbox
    directory, _ = project(root, metadata={"publish_date": "2020-01-02"})
    assert list(cleanup.candidate_dates(root)) == []
    assert directory.exists()


def test_symlink_and_quarantine_are_not_candidates(sandbox):
    root, _ = sandbox
    directory, _ = project(root, "projects/_failed_generation_recovered", metadata={"date": DATE})
    (root / "projects" / PID).symlink_to(directory, target_is_directory=True)
    trash = root / "projects/_trash" / "cand_trash"
    trash.mkdir(parents=True)
    assert list(cleanup.candidate_dates(root)) == []
    assert directory.exists() and trash.exists()


def test_malformed_queue_and_unavailable_store_fail_closed(sandbox):
    root, config = sandbox
    directory, _ = project(root)
    assert cleanup.main(["--apply"]) == 1
    assert directory.exists()
    config.write_text("invalid json")
    assert cleanup.main(["--apply"]) == 1
    assert directory.exists()


def test_cron_runs_independently_and_prevents_overlap():
    cron = (Path(__file__).resolve().parents[1] / "deploy/openmontage.cron").read_text()
    jobs = [line for line in cron.splitlines() if "-m scripts.cleanup_published_projects" in line]
    assert len(jobs) == 1
    assert jobs[0].startswith("35 * * * * ")
    assert "/usr/bin/flock -n " in jobs[0] and "--apply" in jobs[0]
    assert "run_strict" not in jobs[0]


def test_already_verified_project_cleans_without_remote_check(sandbox, monkeypatch):
    root, _ = sandbox
    directory, store = project(root, status="published")
    store.get(publish_key(DATE, PID, "youtube", "short"))["remote_status"] = {
        "privacy_status": "public", "upload_status": "processed",
    }
    remote = Mock(side_effect=AssertionError("Already verified; no API needed"))
    monkeypatch.setattr(YoutubePublisher, "check_video_published", remote)
    assert cleanup.sweep(apply=True, store=store) == 0
    assert not directory.exists()
    remote.assert_not_called()


def test_cli_defaults_to_inspection(monkeypatch):
    sweep = Mock(return_value=0)
    monkeypatch.setattr(cleanup, "sweep", sweep)
    assert cleanup.main([]) == 0
    sweep.assert_called_once_with(apply=False)
