"""Tests for post-publish project cleanup and duplicate protection enforcement."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.publish_active_projects import deactivate_project
from tools.publish_store import publish_key, file_sha256


class FakeStore:
    def __init__(self, records):
        self.records = records

    def get(self, key):
        return self.records.get(key)

    def mark_published(self, key, **kwargs):
        rec = dict(self.records.get(key, {}))
        rec["status"] = "published"
        rec.update(kwargs)
        self.records[key] = rec
        return rec


def make_project_with_renders(
    project_dir: Path,
    cut_content: str = "default cut reel",
    full_content: str = "default full reel",
) -> tuple[str, str]:
    renders = project_dir / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    r_cut = renders / "final_reels_vi_9x16.mp4"
    r_cut.write_text(cut_content)
    r_full = renders / "final_full_vi_9x16.mp4"
    r_full.write_text(full_content)
    return file_sha256(r_cut), file_sha256(r_full)


def canonical_records(
    date: str,
    topic: str,
    facebook_status: str,
    cut_hash: str | None = None,
    full_hash: str | None = None,
):
    return {
        publish_key(date, topic, "youtube", "short"): {
            "status": "published",
            "media_sha256": cut_hash or "cut_hash_dummy",
            "remote_status": {"privacy_status": "public", "upload_status": "processed"},
        },
        publish_key(date, topic, "instagram", "reels"): {
            "status": "published",
            "media_sha256": cut_hash or "cut_hash_dummy",
            "remote_status": {"status": "published"},
        },
        publish_key(date, topic, "facebook", "reels"): {
            "status": facebook_status,
            "media_sha256": full_hash or cut_hash or "full_hash_dummy",
            "remote_status": {"status": "published"} if facebook_status == "published" else None,
        },
    }


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

    # Only youtube+instagram published; facebook not published
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

    # Store has ONLY youtube marked as published; instagram and facebook are pending / not published
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

    store = FakeStore({
        publish_key("2026-09-05", project_id, "youtube", "short"): {"status": "published", "media_sha256": h_cut, "remote_status": {"privacy_status": "public", "upload_status": "processed"}},
        publish_key("2026-09-05", project_id, "instagram", "reels"): {"status": "published", "media_sha256": h_cut, "remote_status": {"status": "published"}},
        publish_key("2026-09-05", project_id, "facebook", "reels"): {"status": "published", "media_sha256": h_full, "remote_status": {"status": "published"}},
    })

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

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    archive_file = logs_dir / "published_archive.jsonl"
    with open(archive_file, "w", encoding="utf-8") as f:
        for cdir, pid in [
            (cand_pub, "cand_pub"),
            (cand_ig_pub, "cand_ig_pub"),
            (cand_news_pub, "cand_news_pub"),
        ]:
            h_cut, h_full = make_project_with_renders(cdir, f"cut for {pid}", f"full for {pid}")
            entry = {
                "project_id": pid,
                "cleanup_state": "cleanup_completed",
                "date": "2026-09-27",
                "media_hashes": {
                    "final_reels_vi_9x16.mp4": h_cut,
                    "final_full_vi_9x16.mp4": h_full,
                },
                "platform_records": {
                    "youtube/short": {"status": "published"},
                    "instagram/reels": {"status": "published"},
                    "facebook/reels": {"status": "published"},
                },
            }
            f.write(json.dumps(entry) + "\n")

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)
    # Hermetic interpreter selection: use the running pytest interpreter so the
    # eligibility module resolves regardless of host system-python dependencies.
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

    # Force write_audit_tombstone to fail
    monkeypatch.setattr(pap, "write_audit_tombstone", lambda *args, **kwargs: False)

    store = FakeStore(canonical_records("2026-09-27", "cand_audit_fail", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_audit_fail", store=store, date="2026-09-27")
    assert ok is False
    # Crucial: directory and media must NOT be deleted
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

    res = subprocess.run(
        ["bash", str(script_path), "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert orphan_dir.exists()
    assert orphan_media.exists()


# ==============================================================================
# RIGOROUS ACCEPTANCE REGRESSION TESTS FOR R1 THROUGH R5
# ==============================================================================

def test_r1_reconcile_youtube_private_processed_stays_pending(tmp_path):
    """R1: Private processed YouTube video must NOT be accepted as published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_priv_proc"}
    })
    rec = store.get("rec1")

    # Mock YoutubePublisher returning private processed
    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "video_id": "yt_priv_proc",
            "privacy_status": "private",  # NOT public!
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
    """R1: Elapsed time alone (e.g. past schedule + 15 min grace) must never authorize published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    # Scheduled 3 hours ago
    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "platform": "youtube", "video_id": "yt_stale_sched"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = None  # Remote check failed or unverified
        res = reconcile_scheduled_record(store, "rec1", rec)
        # MUST remain scheduled
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
        mock_check.return_value = None  # Remote API unverified
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



def test_r2_inspection_and_dry_run_are_strictly_read_only(tmp_path):
    """R2: Eligibility inspection must be strictly read-only and never mutate store or disk."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_r2_inspect"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    # Mock store that raises error if mark_published is called
    class StrictReadOnlyStore:
        def __init__(self):
            self.records = {
                publish_key("2026-09-27", pid, "youtube", "short"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "yt1"},
                publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "ig1"},
                publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "fb1"},
            }

        def get(self, key):
            return self.records.get(key)

        def mark_published(self, *args, **kwargs):
            raise AssertionError("Mutation called during read-only inspection!")

    store = StrictReadOnlyStore()
    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "destinations_incomplete" in reason
    # Confirm store records were not mutated
    for rec in store.records.values():
        assert rec["status"] == "scheduled"


def test_r3_cleanup_fails_closed_when_stored_hash_missing(tmp_path, monkeypatch):
    """R3: Missing media_sha256 in publication record must fail closed and block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_missing_hash"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_missing_hash"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_missing_hash", "publish_date": "2026-09-27"}))
    make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    # Store records are marked published but MISSING media_sha256
    store = FakeStore({
        publish_key("2026-09-27", "cand_missing_hash", "youtube", "short"): {"status": "published"},
        publish_key("2026-09-27", "cand_missing_hash", "instagram", "reels"): {"status": "published"},
        publish_key("2026-09-27", "cand_missing_hash", "facebook", "reels"): {"status": "published"},
    })

    ok = deactivate_project("cand_missing_hash", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_cleanup_fails_closed_when_render_file_missing(tmp_path, monkeypatch):
    """R3: Missing local render file must fail closed and block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_no_render"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_no_render"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_no_render", "publish_date": "2026-09-27"}))
    # Do NOT create renders directory

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_no_render", "published", cut_hash="somehash", full_hash="somehash"))

    ok = deactivate_project("cand_no_render", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_cleanup_fails_closed_when_hash_mismatches(tmp_path, monkeypatch):
    """R3: Mismatched media hash between local render and store must block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_mismatch_hash"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_mismatch_hash"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_mismatch_hash", "publish_date": "2026-09-27"}))
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    # Store recorded a different hash for facebook
    store = FakeStore(canonical_records("2026-09-27", "cand_mismatch_hash", "published", cut_hash=h_cut, full_hash="tampered_hash_value"))

    ok = deactivate_project("cand_mismatch_hash", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_exact_asset_per_platform_binding(tmp_path):
    """R3: Exact platform routes must bind to their specific render (YT/IG -> cut, FB -> full)."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_platform_routes"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    h_cut, h_full = make_project_with_renders(pdir, "cut content", "full story content")
    assert h_cut != h_full

    # Store with cut hash assigned to FB (wrong asset)
    yt_proof = {"privacy_status": "public", "upload_status": "processed"}
    meta_proof = {"status": "published"}
    wrong_store = FakeStore({
        publish_key("2026-09-27", pid, "youtube", "short"): {"status": "published", "media_sha256": h_cut, "remote_status": dict(yt_proof)},
        publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "published", "media_sha256": h_cut, "remote_status": dict(meta_proof)},
        publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "published", "media_sha256": h_cut, "remote_status": dict(meta_proof)},  # Wrong! FB expects h_full
    })

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=wrong_store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "media_hash_mismatch for facebook/reels" in reason

    # Correct store
    correct_store = FakeStore({
        publish_key("2026-09-27", pid, "youtube", "short"): {"status": "published", "media_sha256": h_cut, "remote_status": dict(yt_proof)},
        publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "published", "media_sha256": h_cut, "remote_status": dict(meta_proof)},
        publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "published", "media_sha256": h_full, "remote_status": dict(meta_proof)},
    })
    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=correct_store, date="2026-09-27", root=tmp_path)
    assert eligible is True


def test_r3_archive_fallback_rejects_missing_hashes_when_media_present(tmp_path):
    """R3: Archive fallback must reject present media if tombstone lacks media_hashes."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_no_hash"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {"youtube/short": {"status": "published"}, "instagram/reels": {"status": "published"}, "facebook/reels": {"status": "published"}},
        # media_hashes missing!
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_media_hashes_fail_closed" in reason


def test_r3_archive_fallback_rejects_hash_mismatch(tmp_path):
    """R3: Archive fallback must reject present media if local file hash differs from tombstone."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_mismatch"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {"youtube/short": {"status": "published"}, "instagram/reels": {"status": "published"}, "facebook/reels": {"status": "published"}},
        "media_hashes": {"final_reels_vi_9x16.mp4": "old_cut_hash", "final_full_vi_9x16.mp4": h_full},
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_hash_mismatch_with_current_media" in reason


def test_r4_completion_audit_write_failure_surfaces_error(tmp_path, monkeypatch):
    """R4: If post-deletion audit tombstone write fails, deactivate_project surfaces failure."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_post_audit_fail"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_post_audit_fail"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    # Allow pending tombstone, but fail on completed tombstone
    original_write = pap.write_audit_tombstone
    def mock_write(project_id, project_dir, **kwargs):
        if kwargs.get("status") == "cleanup_completed":
            return False
        return original_write(project_id, project_dir, **kwargs)

    monkeypatch.setattr(pap, "write_audit_tombstone", mock_write)

    store = FakeStore(canonical_records("2026-09-27", "cand_post_audit_fail", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_post_audit_fail", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False


def test_r4_interrupted_finalization_with_new_media_fails_closed(tmp_path, monkeypatch):
    """R4: If cleanup was interrupted and newly generated media appears, retry refuses deletion."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_new_media"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_new_media"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text("{}")
    # Newly generated media with different content
    h_cut, h_full = make_project_with_renders(pdir, "new newly rendered cut", "new full")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    # Store still has old hashes from previous generation
    store = FakeStore(canonical_records("2026-09-27", "cand_new_media", "published", cut_hash="old_generation_cut_hash", full_hash="old_full"))
    ok = deactivate_project("cand_new_media", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r5_explicit_path_duplicate_is_rejected(tmp_path, monkeypatch):
    """R5: Explicit path cannot bypass duplicate location rejection."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_dup_bypass"}]}), encoding="utf-8")

    p1 = tmp_path / "projects" / "cand_dup_bypass"
    p1.mkdir(parents=True)
    p2 = tmp_path / "projects_news" / "cand_dup_bypass"
    p2.mkdir(parents=True)

    h_cut, h_full = make_project_with_renders(p1)
    make_project_with_renders(p2)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_dup_bypass", "published", cut_hash=h_cut, full_hash=h_full))
    # Explicitly pass p1
    ok = deactivate_project("cand_dup_bypass", project_dir=p1, store=store, date="2026-09-27")
    assert ok is False
    assert p1.exists()
    assert p2.exists()


def test_r5_ancestor_symlink_is_rejected(tmp_path, monkeypatch):
    """R5: Reject paths whose parent/ancestor directory is a symlink."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_parent_sym"}]}), encoding="utf-8")

    real_base = tmp_path / "some_external_dir"
    real_base.mkdir()
    sym_parent = tmp_path / "projects" / "instagram"
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    sym_parent.symlink_to(real_base, target_is_directory=True)

    target_dir = sym_parent / "cand_parent_sym"
    target_dir.mkdir()
    h_cut, h_full = make_project_with_renders(target_dir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_parent_sym", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_parent_sym", project_dir=target_dir, store=store, date="2026-09-27")
    assert ok is False
    assert target_dir.exists()


def test_r5_metadata_id_mismatch_is_rejected(tmp_path, monkeypatch):
    """R5: Reject cleanup if publish_metadata.json contains a conflicting ID."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_meta_mismatch"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_meta_mismatch"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_different_victim"}))
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_meta_mismatch", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_meta_mismatch", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r1_reconcile_youtube_public_uploaded_not_processed_stays_pending(tmp_path):
    """R1: YouTube status with upload_status='uploaded' (processing incomplete) must NOT mark published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_uploading"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "video_id": "yt_uploading",
            "privacy_status": "public",
            "upload_status": "uploaded",  # Not processed!
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_missing_fields_stays_pending(tmp_path):
    """R1: YouTube status with missing privacy_status or upload_status must NOT mark published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_incomplete"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        # Missing privacy_status
        mock_check.return_value = {
            "video_id": "yt_incomplete",
            "upload_status": "processed",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"

        # Missing upload_status
        mock_check.return_value = {
            "video_id": "yt_incomplete",
            "privacy_status": "public",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"


def test_publisher_level_api_failure_oembed_success_returns_unverified_oembed(monkeypatch, tmp_path):
    """Finding 5: Publisher-level test: API failure with oEmbed success returns unverified_oembed structure."""
    import io
    import urllib.error
    import urllib.request
    from tools.publishers.youtube_publisher import YoutubePublisher

    # Set up dummy env
    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text('{"installed": {}}')
    token_file = tmp_path / "youtube_token.json"
    token_file.write_text('{"token": "dummy"}')
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token_file))

    # Mock _get_authenticated_service to raise API error
    def mock_get_auth(self, s, t):
        raise RuntimeError("HttpError 403: insufficientPermissions")

    monkeypatch.setattr(YoutubePublisher, "_get_authenticated_service", mock_get_auth)

    # Mock oEmbed response
    class MockOembedResponse:
        def __init__(self):
            self.status = 200
        def read(self):
            return b'{"title": "Sample Title", "author_name": "Sample Author"}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: MockOembedResponse())

    pub = YoutubePublisher()
    result = pub.check_video_published("vid_pub_test")

    assert result.get("status") == "unverified_oembed"
    assert result.get("video_id") == "vid_pub_test"
    assert result.get("via_oembed") is True
    assert result.get("title") == "Sample Title"
    assert result.get("author_name") == "Sample Author"
    # CRITICAL SAFETY: Must NOT counterfeit API status fields
    assert "privacy_status" not in result
    assert "upload_status" not in result


def test_publisher_level_api_and_oembed_failure_returns_structured_error(monkeypatch, tmp_path):
    """Finding 5: When both API and oEmbed fail, check_video_published returns structured error."""
    import urllib.error
    import urllib.request
    from tools.publishers.youtube_publisher import YoutubePublisher

    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text('{"installed": {}}')
    token_file = tmp_path / "youtube_token.json"
    token_file.write_text('{"token": "dummy"}')
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token_file))

    def mock_get_auth(self, s, t, *args, **kwargs):
        raise ValueError("AUTH_REQUIRED: Please authenticate by visiting URL")

    monkeypatch.setattr(YoutubePublisher, "_get_authenticated_service", mock_get_auth)

    def mock_urlopen(*args, **kwargs):
        raise urllib.error.URLError("Not found 404")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    pub = YoutubePublisher()
    result = pub.check_video_published("vid_fail_test")

    assert result.get("status") == "error"
    assert result.get("error_type") == "auth_required"
    assert "AUTH_REQUIRED" in result.get("error", "")


def test_real_publish_store_mark_published_accepts_verified_at_and_remote_status(monkeypatch):
    """Finding 1: Verify real PublishStore.mark_published accepts verified_at & remote_status without TypeError."""
    from tools.publish_store import PublishStore

    # Mock service account and session to isolate from real network/Firestore
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", json.dumps({"project_id": "test-project"}))

    captured_updates = {}
    class MockResponse:
        status_code = 200
        def json(self):
            return {"fields": {}}

    class MockSession:
        def patch(self, url, params=None, json=None, timeout=None):
            captured_updates.update(json.get("fields", {}))
            return MockResponse()

    monkeypatch.setattr("tools.publish_store.Credentials.from_service_account_info", lambda *args, **kwargs: None)
    monkeypatch.setattr("tools.publish_store.AuthorizedSession", lambda creds: MockSession())

    store = PublishStore()
    remote_st = {"privacy_status": "public", "upload_status": "processed"}
    res = store.mark_published(
        "test_key_1",
        video_id="v123",
        video_url="https://youtube.com/watch?v=v123",
        published_at="2026-10-01T09:15:00Z",
        verified_at="2026-10-01T09:20:00Z",
        remote_status=remote_st,
    )
    # Ensure call succeeded and fields were formatted for Firestore
    assert "status" in captured_updates
    assert captured_updates["status"] == {"stringValue": "published"}
    assert "verified_at" in captured_updates
    assert captured_updates["verified_at"] == {"stringValue": "2026-10-01T09:20:00Z"}
    assert "remote_status" in captured_updates


def test_cleanup_boundary_rejects_historical_records_lacking_authoritative_proof(tmp_path):
    """Finding 2: Projects with records marked 'published' but lacking public release proof must fail closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_unverified_hist"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    # Store has status='published' but NO remote_status or unlisted remote_status
    store = FakeStore({
        publish_key("2026-09-27", pid, "youtube", "short"): {
            "status": "published",
            "media_sha256": h_cut,
            # No remote_status or unlisted privacy_status
            "remote_status": {"privacy_status": "unlisted", "upload_status": "processed"},
        },
        publish_key("2026-09-27", pid, "instagram", "reels"): {
            "status": "published",
            "media_sha256": h_cut,
            "remote_status": {"status": "published"},
        },
        publish_key("2026-09-27", pid, "facebook", "reels"): {
            "status": "published",
            "media_sha256": h_full,
            "remote_status": {"status": "published"},
        },
    })

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "missing_authoritative_public_evidence" in reason


def test_r3_current_store_pending_or_failed_records_cannot_be_overridden_by_archive(tmp_path):
    """R3: Historical archive tombstone must NOT override current pending/failed store records."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_override_prevented"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    # Archive has a historical cleanup_completed entry
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
            "facebook/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    # Current store has one record still scheduled
    active_store = FakeStore({
        publish_key("2026-09-27", pid, "youtube", "short"): {"status": "published", "media_sha256": h_cut},
        publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "scheduled", "video_id": "ig1"},
        publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "published", "media_sha256": h_full},
    })

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=active_store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "destinations_incomplete" in reason
    assert "instagram/reels (status=scheduled)" in reason


def test_r3_archive_fallback_rejects_missing_date_when_media_present(tmp_path):
    """R3: Archive tombstone with missing date must fail closed when media is present."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_no_date"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": None,  # Missing date!
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
            "facebook/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_date_fail_closed" in reason


def test_r3_archive_fallback_rejects_empty_platform_records_when_media_present(tmp_path):
    """R3: Archive tombstone with empty platform_records must fail closed when media is present."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_empty_plat"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {},  # Empty platform records!
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_or_empty_platform_records_fail_closed" in reason


def test_r3_archive_fallback_rejects_missing_required_route_in_archive(tmp_path):
    """R3: Archive tombstone missing required platform must fail closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_missing_route"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    # Lacks facebook/reels
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_incomplete_destinations_fail_closed" in reason


def test_r3_archive_fallback_valid_fully_evidenced_recovery_allows_cleanup(tmp_path):
    """R3: Valid archive tombstone with matching hashes across all routes allows cleanup."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_valid_full"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
            "facebook/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is True
    assert reason == "verified_via_audit_archive"


def test_r3_archive_fallback_already_absent_directory_recovery_allows_idempotent_cleanup(tmp_path):
    """R3: Archive tombstone allows idempotent recovery when directory is already deleted."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_already_deleted"
    pdir = tmp_path / "projects" / pid
    # Do NOT create pdir (already absent)

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
            "facebook/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": "cut_hash_1",
            "final_full_vi_9x16.mp4": "full_hash_1",
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is True
    assert reason == "verified_via_audit_archive"


def test_r3_archive_fallback_newly_present_render_file_fails_closed(tmp_path):
    """R3: Newly present/unrecognized render file in project not accounted for in archive fails closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_new_file"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    # Add extra new unrecorded render file
    extra_render = pdir / "renders" / "bonus_render.mp4"
    extra_render.write_text("bonus unrecorded content")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(json.dumps({
        "project_id": pid,
        "cleanup_state": "cleanup_completed",
        "date": "2026-09-27",
        "platform_records": {
            "youtube/short": {"status": "published"},
            "instagram/reels": {"status": "published"},
            "facebook/reels": {"status": "published"},
        },
        "media_hashes": {
            "final_reels_vi_9x16.mp4": h_cut,
            "final_full_vi_9x16.mp4": h_full,
        },
    }) + "\n")

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "unrecognized_new_media_file_in_archive_check" in reason

