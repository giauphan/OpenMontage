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
