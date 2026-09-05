"""Tests for post-publish project cleanup and duplicate protection enforcement."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.publish_active_projects import deactivate_project


def test_deactivate_project_removes_schedule_and_directory(tmp_path, monkeypatch):
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_id = "cand_test123"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()
    (target_project_dir / "publish_metadata.json").write_text("{}")

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
    deactivate_project(project_id)

    assert not target_project_dir.exists()
    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids
    assert "cand_other" in active_ids
