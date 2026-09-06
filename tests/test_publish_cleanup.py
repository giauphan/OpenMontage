"""Tests for post-publish project cleanup and duplicate protection enforcement."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.publish_active_projects import deactivate_project
from tools.publish_store import publish_key


class FakeStore:
    def __init__(self, records):
        self.records = records

    def get(self, key):
        return self.records.get(key)


def canonical_records(date: str, topic: str, facebook_status: str):
    return {
        publish_key(date, topic, "youtube", "short"): {"status": "published"},
        publish_key(date, topic, "instagram", "reels"): {"status": "published"},
        publish_key(date, topic, "facebook", "reels"): {"status": facebook_status},
    }


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


def test_deactivate_project_blocks_on_incomplete_canonical_firebase_records(tmp_path, monkeypatch):
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
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    # Only youtube+instagram published; facebook not published
    store = FakeStore(canonical_records("2026-09-05", project_id, "failed"))

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

    initial_schedule = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-09-05", "publish_time": "09:15"},
        ]
    }
    config_file.write_text(json.dumps(initial_schedule, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-05", project_id, "published"))

    ok = deactivate_project(project_id, store=store, date="2026-09-05")
    assert ok is True
    assert not target_project_dir.exists()

    updated_schedule = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [
        item.get("project_id") if isinstance(item, dict) else item
        for item in updated_schedule.get("active_projects", [])
    ]
    assert project_id not in active_ids
