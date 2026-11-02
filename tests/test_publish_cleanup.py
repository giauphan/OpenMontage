"""Tests for post-publish project cleanup and duplicate protection enforcement."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.publish_active_projects import deactivate_project
from tools.publish_store import publish_key, file_sha256
from tests._publish_cleanup_helpers import (
    FakeStore,
    canonical_records,
    make_project_with_renders,
    write_archive_entry,
)


def test_deactivate_project_removes_schedule_and_directory(tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_id = "cand_test123"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()
    (target_project_dir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(target_project_dir)

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
            {"project_id": "cand_other", "publish_date": "2026-09-05", "publish_time": "14:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    assert target_project_dir.exists()
    store = FakeStore(canonical_records("2026-09-05", project_id, "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project(project_id, store=store, date="2026-09-05")
    assert ok is True

    assert not target_project_dir.exists()
    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids
    assert "cand_other" in active_ids


def test_deactivate_project_blocks_on_incomplete_canonical_firebase_records(tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_id = "cand_test123"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()
    (target_project_dir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(target_project_dir)

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-05", project_id, "failed", cut_hash=h_cut, full_hash=h_full))

    ok = deactivate_project(project_id, store=store, date="2026-09-05")
    assert ok is False
    assert target_project_dir.exists()

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id in active_ids


def test_deactivate_project_allows_on_all_three_published(tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_id = "cand_test123"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()
    (target_project_dir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(target_project_dir)

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-05", project_id, "published", cut_hash=h_cut, full_hash=h_full))

    ok = deactivate_project(project_id, store=store, date="2026-09-05")
    assert ok is True
    assert not target_project_dir.exists()

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids


def test_youtube_success_instagram_pending_retains_schedule_and_directory(tmp_path, monkeypatch):
    config_file = tmp_path / "config" / "publish_schedule.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    project_id = "cand_multi_platform"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()
    h_cut, h_full = make_project_with_renders(target_project_dir)
    (target_project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": project_id,
        "ig_reels": "Instagram Reel Title",
        "fb_reels": "Facebook Reel Title",
    }))

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore({
        publish_key("2026-09-05", project_id, "youtube", "short"): {"status": "published", "media_sha256": h_cut, "remote_status": {"privacy_status": "public", "upload_status": "processed"}},
        publish_key("2026-09-05", project_id, "instagram", "reels"): {"status": "pending", "media_sha256": h_cut},
        publish_key("2026-09-05", project_id, "facebook", "reels"): {"status": "pending", "media_sha256": h_full},
    })

    ok = deactivate_project(project_id, project_dir=target_project_dir, store=store, date="2026-09-05")
    assert ok is False
    assert target_project_dir.exists()

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id in active_ids


@pytest.mark.parametrize("loc_dir", ["projects", "projects_news", "projects/instagram"])
def test_final_platform_success_cleans_across_all_locations(tmp_path, monkeypatch, loc_dir):
    config_file = tmp_path / "config" / "publish_schedule.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    parent_dir = tmp_path / loc_dir
    parent_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects_news").mkdir(parents=True, exist_ok=True)

    project_id = f"cand_test_{loc_dir.replace('/', '_')}"
    target_project_dir = parent_dir / project_id
    target_project_dir.mkdir()
    h_cut, h_full = make_project_with_renders(target_project_dir)
    (target_project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": project_id,
        "ig_reels": "Instagram Reel",
    }))

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-05", project_id, "published", cut_hash=h_cut, full_hash=h_full))

    ok = deactivate_project(project_id, project_dir=target_project_dir, store=store, date="2026-09-05")
    assert ok is True
    assert not target_project_dir.exists()

    if loc_dir == "projects/instagram":
        assert not (tmp_path / "projects" / "instagram").exists()

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids

    archive_file = tmp_path / "logs" / "published_archive.jsonl"
    assert archive_file.is_file()
    lines = [json.loads(line) for line in archive_file.read_text(encoding="utf-8").strip().splitlines()]
    completed_entries = [e for e in lines if e.get("project_id") == project_id and e.get("cleanup_state") == "cleanup_completed"]
    assert len(completed_entries) >= 1


def test_idempotent_cleanup_handles_already_deleted_folders(tmp_path, monkeypatch):
    config_file = tmp_path / "config" / "publish_schedule.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects_news").mkdir(parents=True, exist_ok=True)

    project_id = "cand_already_deleted"
    non_existent_dir = tmp_path / "projects" / project_id

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore({
        publish_key("2026-09-05", project_id, "youtube", "short"): {"status": "published", "remote_status": {"privacy_status": "public", "upload_status": "processed"}},
        publish_key("2026-09-05", project_id, "instagram", "reels"): {"status": "published", "remote_status": {"status": "published"}},
        publish_key("2026-09-05", project_id, "facebook", "reels"): {"status": "published", "remote_status": {"status": "published"}},
    })

    ok = deactivate_project(project_id, project_dir=non_existent_dir, store=store, date="2026-09-05")
    assert ok is True

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids

    archive_file = tmp_path / "logs" / "published_archive.jsonl"
    assert archive_file.is_file()
    lines = [json.loads(line) for line in archive_file.read_text(encoding="utf-8").strip().splitlines()]
    completed_entries = [e for e in lines if e.get("project_id") == project_id and e.get("cleanup_state") == "cleanup_completed"]
    assert len(completed_entries) >= 1


def test_stale_script_dry_run_identifies_published_vs_pending(tmp_path):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "clear_stale_projects.sh"
    config_file = tmp_path / "config" / "publish_schedule.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    projects_news_dir = tmp_path / "projects_news"
    projects_news_dir.mkdir(parents=True, exist_ok=True)
    ig_dir = projects_dir / "instagram"
    ig_dir.mkdir(parents=True, exist_ok=True)

    cand_active = projects_dir / "cand_active"
    cand_active.mkdir()
    (cand_active / "publish_metadata.json").write_text("{}")

    cand_retry = projects_dir / "cand_retry"
    cand_retry.mkdir()
    (cand_retry / "publish_metadata.json").write_text("{}")

    cand_pub = projects_dir / "cand_pub"
    cand_pub.mkdir()
    (cand_pub / "publish_metadata.json").write_text(json.dumps({"publish_date": "2026-09-27"}))

    cand_ig_pub = ig_dir / "cand_ig_pub"
    cand_ig_pub.mkdir()
    (cand_ig_pub / "publish_metadata.json").write_text(json.dumps({"publish_date": "2026-09-27"}))

    cand_news_pub = projects_news_dir / "cand_news_pub"
    cand_news_pub.mkdir()
    (cand_news_pub / "publish_metadata.json").write_text(json.dumps({"publish_date": "2026-09-27"}))

    schedule_data = {
        "active_projects": [
            {"project_id": "cand_active", "publish_date": "2026-09-27", "publish_time": "09:15"},
            {"project_id": "cand_retry", "publish_date": "2026-09-27", "publish_time": "09:15", "retry_count": 1},
        ]
    }
    config_file.write_text(json.dumps(schedule_data, indent=2), encoding="utf-8")

    for cdir, pid in [
        (cand_pub, "cand_pub"),
        (cand_ig_pub, "cand_ig_pub"),
        (cand_news_pub, "cand_news_pub"),
    ]:
        h_cut, h_full = make_project_with_renders(cdir, f"cut for {pid}", f"full for {pid}")
        write_archive_entry(
            tmp_path,
            pid,
            media_hashes={
                "final_reels_vi_9x16.mp4": h_cut,
                "final_full_vi_9x16.mp4": h_full,
            },
        )

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)
    env["PYTHON_BIN"] = sys.executable

    res = subprocess.run(
        ["bash", str(script_path), "--dry-run", "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=True,
    )

    out = res.stdout
    assert "Would remove verified published stale project: cand_pub" in out
    assert "Would remove verified published stale project: cand_ig_pub" in out
    assert "Would remove verified published stale project: cand_news_pub" in out
    assert "cand_active" not in out
    assert "cand_retry" not in out

    assert cand_active.exists()
    assert cand_retry.exists()
    assert cand_pub.exists()
    assert cand_ig_pub.exists()
    assert cand_news_pub.exists()


def test_schedule_file_locking_prevents_concurrent_races(tmp_path):
    import concurrent.futures
    import fcntl
    from scripts.publish_active_projects import locked_schedule

    config_file = tmp_path / "publish_schedule.json"
    initial = {"active_projects": []}
    config_file.write_text(json.dumps(initial, indent=2), encoding="utf-8")

    with locked_schedule(config_file):
        lock_path = config_file.with_suffix(".lock")
        assert lock_path.exists()
        f2 = open(lock_path, "w")
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(f2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            f2.close()

    def update_schedule(worker_id: int):
        with locked_schedule(config_file):
            content = json.loads(config_file.read_text(encoding="utf-8"))
            content["active_projects"].append({
                "project_id": f"cand_worker_{worker_id}",
                "publish_date": "2026-09-27",
                "publish_time": "09:15",
            })
            temp = config_file.with_suffix(".tmp")
            temp.write_text(json.dumps(content, indent=2), encoding="utf-8")
            temp.replace(config_file)

    num_workers = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_schedule, i) for i in range(num_workers)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    final_content = json.loads(config_file.read_text(encoding="utf-8"))
    worker_pids = {item["project_id"] for item in final_content["active_projects"]}
    expected_pids = {f"cand_worker_{i}" for i in range(num_workers)}
    assert worker_pids == expected_pids
    assert len(final_content["active_projects"]) == num_workers


def test_deactivate_project_detects_duplicate_directories(tmp_path, monkeypatch):
    """F05 / R5: Duplicate project directories across locations require reconciliation and block deletion."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_dup"}]}), encoding="utf-8")

    p1 = tmp_path / "projects" / "cand_dup"
    p1.mkdir(parents=True)
    p2 = tmp_path / "projects_news" / "cand_dup"
    p2.mkdir(parents=True)

    h_cut, h_full = make_project_with_renders(p1)
    make_project_with_renders(p2)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_dup", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_dup", store=store, date="2026-09-27")
    assert ok is False
    assert p1.exists()
    assert p2.exists()


def test_deactivate_project_rejects_symlink_directory(tmp_path, monkeypatch):
    """F05 / R5: Refuse deletion of symlink project directories."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_sym"}]}), encoding="utf-8")

    real_dir = tmp_path / "real_target"
    real_dir.mkdir()
    h_cut, h_full = make_project_with_renders(real_dir)
    symlink_dir = tmp_path / "projects" / "cand_sym"
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    symlink_dir.symlink_to(real_dir, target_is_directory=True)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_sym", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_sym", project_dir=symlink_dir, store=store, date="2026-09-27")
    assert ok is False
    assert real_dir.exists()
    assert symlink_dir.exists()


def test_deactivate_project_rejects_unauthorized_parent_and_traversal(tmp_path, monkeypatch):
    """F05 / R5: Refuse deletion of directories outside authorized project roots."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_outside"}]}), encoding="utf-8")

    outside_dir = tmp_path / "outside_projects" / "cand_outside"
    outside_dir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(outside_dir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_outside", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_outside", project_dir=outside_dir, store=store, date="2026-09-27")
    assert ok is False
    assert outside_dir.exists()


def test_audit_write_failure_aborts_deletion(tmp_path, monkeypatch):
    """F05 / R4: Failure to persist durable audit tombstone aborts deletion before removing files."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_audit_fail"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_audit_fail"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "write_audit_tombstone", lambda *args, **kwargs: False)

    store = FakeStore(canonical_records("2026-09-27", "cand_audit_fail", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_audit_fail", store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()
    assert (pdir / "renders" / "final_reels_vi_9x16.mp4").exists()


def test_stale_cleanup_never_purges_unpublished_candidate_regardless_of_age_and_all(tmp_path):
    """F02: Unknown or unpublished candidates survive sweeps even if >24 hours old and --all is passed."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "clear_stale_projects.sh"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True)

    orphan_dir = projects_dir / "cand_old_orphan"
    orphan_dir.mkdir()
    (orphan_dir / "publish_metadata.json").write_text("{}")
    orphan_media = orphan_dir / "final.mp4"
    orphan_media.write_text("old unpublished media")

    past_time = time.time() - (48 * 3600)
    os.utime(orphan_dir, (past_time, past_time))

    schedule_file = tmp_path / "config" / "publish_schedule.json"
    schedule_file.parent.mkdir(parents=True)
    schedule_file.write_text(json.dumps({"active_projects": []}), encoding="utf-8")

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)

    subprocess.run(
        ["bash", str(script_path), "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert orphan_dir.exists()
    assert orphan_media.exists()


# ==============================================================================
# RIGOROUS ACCEPTANCE REGRESSION TESTS FOR R1
# ==============================================================================

def test_r1_reconcile_youtube_private_processed_stays_pending(tmp_path):
    """R1: Private processed YouTube video must NOT be accepted as published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_priv_proc"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "video_id": "yt_priv_proc",
            "privacy_status": "private",
            "upload_status": "processed",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_api_error_stays_pending(tmp_path):
    """R1: YouTube API errors/unavailable must leave scheduled record pending."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_err"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "status": "error",
            "error_type": "http_error",
            "status_code": 403,
            "error": "<HttpError 403 when requesting ... returned 'insufficientPermissions'>",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_auth_required_stays_pending(tmp_path):
    """R1: YouTube AUTH_REQUIRED error leaves scheduled record pending."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_auth_req"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "status": "error",
            "error_type": "auth_required",
            "error": "AUTH_REQUIRED: Please authenticate by visiting https://accounts.google.com/o/oauth2/auth...",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_oembed_fallback_never_authorizes_published(tmp_path):
    """R1: Non-authoritative oEmbed response on API failure must never authorize publication."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_oembed"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "status": "unverified_oembed",
            "video_id": "yt_oembed",
            "title": "Test Title",
            "author_name": "Test Channel",
            "via_oembed": True,
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_elapsed_time_never_authorizes_published(tmp_path):
    """R1: Elapsed time alone must never authorize published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "youtube", "video_id": "yt_stale_sched"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = None
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_meta_elapsed_time_never_authorizes_published(tmp_path):
    """R1: Elapsed time + ID alone on Meta routes must never authorize published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec_ig": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "instagram", "video_id": "ig_123"},
        "rec_fb": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "facebook", "video_id": "fb_123"},
    })

    with patch("tools.publishers.meta_publisher.MetaPublisher.check_media_published") as mock_check:
        mock_check.return_value = None
        res_ig = reconcile_scheduled_record(store, "rec_ig", store.get("rec_ig"))
        res_fb = reconcile_scheduled_record(store, "rec_fb", store.get("rec_fb"))
        assert res_ig.get("status") == "scheduled"
        assert res_fb.get("status") == "scheduled"


def test_r1_reconcile_remote_verified_public_authorizes_published(tmp_path):
    """R1: Authoritative public visibility marks record published with verification metadata."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec_yt": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "youtube", "video_id": "yt_pub"},
        "rec_ig": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "instagram", "video_id": "ig_pub"},
    })

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_yt, \
         patch("tools.publishers.meta_publisher.MetaPublisher.check_media_published") as mock_ig:
        mock_yt.return_value = {"privacy_status": "public", "upload_status": "processed"}
        mock_ig.return_value = {"status": "published", "shortcode": "xyz123"}

        res_yt = reconcile_scheduled_record(store, "rec_yt", store.get("rec_yt"))
        assert res_yt.get("status") == "published"
        assert res_yt.get("verified_at") is not None

        res_ig = reconcile_scheduled_record(store, "rec_ig", store.get("rec_ig"))
        assert res_ig.get("status") == "published"
        assert res_ig.get("verified_at") is not None


def test_r1_reconcile_youtube_verified_oembed_promotes_published(tmp_path):
    """R1: Verified oEmbed with matching title and passed schedule promotes scheduled record to published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec_yt": {
            "status": "scheduled",
            "scheduled_for": "2026-09-27T00:00:00Z",
            "platform": "youtube",
            "video_id": "yt_oembed_valid",
            "title": "Bản tin AI hôm nay #tintuc #ai",
        },
    })

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_yt:
        mock_yt.return_value = {
            "status": "unverified_oembed",
            "video_id": "yt_oembed_valid",
            "title": "Bản tin AI hôm nay #tintuc #ai #Shorts",
            "author_name": "Tech Channel",
            "via_oembed": True,
        }

        res_yt = reconcile_scheduled_record(store, "rec_yt", store.get("rec_yt"))
        assert res_yt.get("status") == "published"
        assert res_yt.get("verified_at") is not None
        assert res_yt.get("remote_status", {}).get("privacy_status") == "public"
        assert res_yt.get("remote_status", {}).get("upload_status") == "processed"
