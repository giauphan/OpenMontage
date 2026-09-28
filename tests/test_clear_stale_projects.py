"""Tests for scripts/clear_stale_projects.sh enforcing the unified cleanup safety contract."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from tools.publish_store import file_sha256

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clear_stale_projects.sh"


def test_clear_stale_preserves_active_and_unverified_removes_verified(tmp_path: Path):
    """Verify clear_stale_projects.sh preserves active projects and unverified projects, removing only verified published."""
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    projects_news_dir = tmp_path / "projects_news"
    logs_dir = tmp_path / "logs"
    for d in (scripts_dir, config_dir, projects_dir, projects_news_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SCRIPT, scripts_dir / "clear_stale_projects.sh")

    # Config with cand_active1 and cand_active2
    config_file = config_dir / "publish_schedule.json"
    config_file.write_text(
        json.dumps(
            {
                "active_projects": [
                    {"project_id": "cand_active1", "publish_date": "2026-09-28", "publish_time": "09:15"},
                    "cand_active2",
                ]
            }
        ),
        encoding="utf-8",
    )

    # 1. Active candidate folders
    (projects_dir / "cand_active1").mkdir()
    (projects_dir / "cand_active2").mkdir()

    # 2. Unverified stale candidate (must NOT be deleted even with --all)
    cand_unverified = projects_dir / "cand_unverified"
    cand_unverified.mkdir()
    (cand_unverified / "publish_metadata.json").write_text("{}")

    # 3. Verified published candidate with renders and archive tombstone
    cand_verified = projects_news_dir / "cand_verified"
    cand_verified.mkdir()
    (cand_verified / "publish_metadata.json").write_text(json.dumps({"publish_date": "2026-09-28"}))
    renders = cand_verified / "renders"
    renders.mkdir()
    r_cut = renders / "final_reels_vi_9x16.mp4"
    r_cut.write_text("cut")
    r_full = renders / "final_full_vi_9x16.mp4"
    r_full.write_text("full")
    h_cut = file_sha256(r_cut)
    h_full = file_sha256(r_full)

    archive_file = logs_dir / "published_archive.jsonl"
    archive_file.write_text(
        json.dumps(
            {
                "project_id": "cand_verified",
                "cleanup_state": "cleanup_completed",
                "date": "2026-09-28",
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
        ) + "\n",
        encoding="utf-8",
    )

    (projects_dir / "other_dir").mkdir()  # Non-candidate dir

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)
    env["PYTHONPATH"] = f"{ROOT}:{tmp_path}:{env.get('PYTHONPATH', '')}"

    res = subprocess.run(
        ["bash", str(SCRIPT), "--all"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    # Active projects must remain
    assert (projects_dir / "cand_active1").is_dir()
    assert (projects_dir / "cand_active2").is_dir()
    # Non-candidate dirs must remain untouched
    assert (projects_dir / "other_dir").is_dir()
    # Unverified candidates must survive sweeps
    assert (projects_dir / "cand_unverified").is_dir()
    # Verified published candidate must be removed
    assert not (projects_news_dir / "cand_verified").exists()


def test_clear_stale_unverified_survives_regardless_of_age(tmp_path: Path):
    """Verify clear_stale_projects.sh never deletes unverified projects regardless of age."""
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    for d in (scripts_dir, config_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SCRIPT, scripts_dir / "clear_stale_projects.sh")

    (config_dir / "publish_schedule.json").write_text(
        json.dumps({"active_projects": []}),
        encoding="utf-8",
    )

    recent_dir = projects_dir / "cand_recent"
    recent_dir.mkdir()

    old_dir = projects_dir / "cand_old"
    old_dir.mkdir()
    # Set mtime to 3 hours ago (180 mins)
    past_time = time.time() - (180 * 60)
    os.utime(old_dir, (past_time, past_time))

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)

    res = subprocess.run(
        ["bash", str(scripts_dir / "clear_stale_projects.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    # Both recent and old unverified candidates must be preserved
    assert recent_dir.is_dir()
    assert old_dir.is_dir()


def test_clear_stale_exits_gracefully_when_no_config(tmp_path: Path):
    """Verify script exits 0 without error when publish_schedule.json is missing."""
    scripts_dir = tmp_path / "scripts"
    projects_dir = tmp_path / "projects"
    for d in (scripts_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SCRIPT, scripts_dir / "clear_stale_projects.sh")
    (projects_dir / "cand_orphan").mkdir()

    env = dict(os.environ)
    env["OPENMONTAGE_ROOT"] = str(tmp_path)

    res = subprocess.run(
        ["bash", str(scripts_dir / "clear_stale_projects.sh"), "--all"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "No publish schedule found" in res.stdout
    assert (projects_dir / "cand_orphan").is_dir()
