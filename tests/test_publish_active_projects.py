import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import scripts.publish_active_projects as pap

@patch("subprocess.run")
def test_publish_active_projects_forwards_date_and_strict(mock_run, tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    
    pid1 = "cand_test1"
    pdir1 = projects_dir / pid1
    pdir1.mkdir()
    (pdir1 / "publish_metadata.json").write_text("{}")
    
    schedule = {
        "active_projects": [
            {"project_id": pid1, "publish_date": "2026-09-06", "publish_time": "09:15"}
        ]
    }
    config_file.write_text(json.dumps(schedule), encoding="utf-8")
    
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: schedule)
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")
    
    # Mock sys.argv
    test_args = ["publish_active_projects.py", "--date", "2026-09-06"]
    with patch("sys.argv", test_args):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        exit_code = pap.main()
        
    assert exit_code == 0
    assert mock_run.call_count == 1
    
    called_args = mock_run.call_args[0][0]
    # Check that `--date 2026-09-06` was passed to publisher
    assert "--date" in called_args
    date_idx = called_args.index("--date")
    assert called_args[date_idx + 1] == "2026-09-06"

@patch("subprocess.run")
def test_slot_publish_uses_explicit_date(mock_run, tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    project_dir = projects_dir / "cand_test1"
    project_dir.mkdir()
    (project_dir / "publish_metadata.json").write_text("{}")
    schedule = {
        "timezone": "Asia/Ho_Chi_Minh",
        "active_projects": [
            {"project_id": "cand_test1", "publish_date": "2026-09-08", "publish_time": "09:15"}
        ],
    }
    config_file.write_text(json.dumps(schedule), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: schedule)
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")
    mock_run.return_value = MagicMock(returncode=0)

    with patch("sys.argv", ["publish_active_projects.py", "--slot", "09:15", "--date", "2026-09-08"]):
        assert pap.main() == 0

    assert mock_run.call_args.args[0][-2:] == ["--date", "2026-09-08"]


def test_slot_never_dispatches_overdue_projects():
    projects = [
        {"project_id": "old", "publish_date": "2026-10-12", "publish_time": "09:15"},
        {"project_id": "earlier", "publish_date": "2026-10-13", "publish_time": "09:15"},
        {"project_id": "current", "publish_date": "2026-10-13", "publish_time": "14:15"},
    ]
    assert pap.scheduled_projects_for_slot(projects, "14:15", "2026-10-13") == [projects[2]]


@patch("subprocess.run")
def test_publish_active_projects_filters_out_wrong_date(mock_run, tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    
    pid1 = "cand_test1"
    pdir1 = projects_dir / pid1
    pdir1.mkdir()
    (pdir1 / "publish_metadata.json").write_text("{}")
    
    schedule = {
        "active_projects": [
            {"project_id": pid1, "publish_date": "2026-09-07", "publish_time": "09:15"}
        ]
    }
    config_file.write_text(json.dumps(schedule), encoding="utf-8")
    
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: schedule)

    test_args = ["publish_active_projects.py", "--date", "2026-09-06"]
    with patch("sys.argv", test_args):
        exit_code = pap.main()
        
    assert exit_code == 0
    assert mock_run.call_count == 0  # no projects matched the date


@patch("subprocess.run")
def test_validation_exit_2_dry_run_is_non_destructive(mock_run, tmp_path, monkeypatch):
    """F04: Validation exit 2 during --dry-run must not delete media or mutate schedule."""
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    pid = "cand_val2_dry"
    pdir = projects_dir / pid
    pdir.mkdir()
    (pdir / "publish_metadata.json").write_text("{}")
    render_file = pdir / "final.mp4"
    render_file.write_text("dummy media content")

    initial_schedule = {
        "active_projects": [
            {"project_id": pid, "publish_date": "2026-09-27", "publish_time": "09:15"}
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")

    mock_run.return_value = MagicMock(returncode=2, stdout="Quality validation failed", stderr="")

    with patch("sys.argv", ["publish_active_projects.py", "--dry-run", "--date", "2026-09-27"]):
        code = pap.main()

    assert code == 2
    # Verify files and directory still exist
    assert pdir.exists()
    assert render_file.exists()
    # Verify schedule is completely unmutated
    after_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    assert after_schedule == initial_schedule


@patch("subprocess.run")
def test_validation_exit_2_non_dry_run_retains_media_and_records_status(mock_run, tmp_path, monkeypatch):
    """F04: Validation exit 2 during non-dry-run must retain media and record validation_rejected."""
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    pid = "cand_val2_live"
    pdir = projects_dir / pid
    pdir.mkdir()
    (pdir / "publish_metadata.json").write_text("{}")
    render_file = pdir / "final.mp4"
    render_file.write_text("dummy media content")

    initial_schedule = {
        "active_projects": [
            {"project_id": pid, "publish_date": "2026-09-27", "publish_time": "09:15"}
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")

    mock_run.return_value = MagicMock(returncode=2, stdout="Quality validation failed", stderr="")

    with patch("sys.argv", ["publish_active_projects.py", "--date", "2026-09-27"]):
        code = pap.main()

    assert code == 2
    # Media must be retained for diagnosis
    assert pdir.exists()
    assert render_file.exists()
    # Status in schedule must be validation_rejected
    after_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    proj_entry = after_schedule["active_projects"][0]
    assert proj_entry["status"] == "validation_rejected"
    assert proj_entry["alert"] == "quality_gate_rejected"


@patch("subprocess.run")
def test_backoff_timing_and_max_retries(mock_run, tmp_path, monkeypatch):
    """F07: Transient publishing failure computes exponential backoff and caps at max retries."""
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    pid = "cand_backoff"
    pdir = projects_dir / pid
    pdir.mkdir()
    (pdir / "publish_metadata.json").write_text("{}")

    initial_schedule = {
        "active_projects": [
            {"project_id": pid, "publish_date": "2026-09-27", "publish_time": "09:15", "retry_count": 0}
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")

    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="503 Service Unavailable")

    # Attempt 1 -> retry_count becomes 1, next_attempt_at set with ~300s delay
    with patch("sys.argv", ["publish_active_projects.py", "--date", "2026-09-27"]):
        assert pap.main() == 1

    sched1 = json.loads(config_file.read_text(encoding="utf-8"))
    item1 = sched1["active_projects"][0]
    assert item1["retry_count"] == 1
    assert "next_attempt_at" in item1
    assert "last_attempt" in item1

    # Attempt 2 -> retry_count becomes 2, next_attempt_at set with ~900s delay
    with patch("sys.argv", ["publish_active_projects.py", "--date", "2026-09-27"]):
        assert pap.main() == 1

    sched2 = json.loads(config_file.read_text(encoding="utf-8"))
    item2 = sched2["active_projects"][0]
    assert item2["retry_count"] == 2

    # Attempt 3 -> reaches max retries (3), status becomes 'failed'
    with patch("sys.argv", ["publish_active_projects.py", "--date", "2026-09-27"]):
        assert pap.main() == 1

    sched3 = json.loads(config_file.read_text(encoding="utf-8"))
    item3 = sched3["active_projects"][0]
    assert item3["retry_count"] == 3
    assert item3["status"] == "failed"
    assert item3["alert"] == "max_retries_exceeded"


@patch("subprocess.run")
def test_auth_failure_marks_auth_blocked(mock_run, tmp_path, monkeypatch):
    """F07: Authentication errors immediately transition to auth_blocked status."""
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    pid = "cand_auth_fail"
    pdir = projects_dir / pid
    pdir.mkdir()
    (pdir / "publish_metadata.json").write_text("{}")

    initial_schedule = {
        "active_projects": [
            {"project_id": pid, "publish_date": "2026-09-27", "publish_time": "09:15", "retry_count": 0}
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setattr(pap, "load_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(pap, "PUBLISHER", tmp_path / "scripts" / "publish_manual_video.py")

    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="OAuthException: invalid_grant")

    with patch("sys.argv", ["publish_active_projects.py", "--date", "2026-09-27"]):
        assert pap.main() == 1

    sched = json.loads(config_file.read_text(encoding="utf-8"))
    item = sched["active_projects"][0]
    assert item["status"] == "auth_blocked"
    assert item["alert"] == "authentication_error_requires_operator_resolution"

