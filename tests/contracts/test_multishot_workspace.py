"""Multi-shot workspace tests (M0, TASK 002).

Tests cover:
  - new project produces required folders
  - existing project not overwritten accidentally
  - safe path handling (no traversal, no absolute path injection)
  - stable shot filenames
  - atomic write/read roundtrip
  - run manifest init/read/mutate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_workspace import (
    PLANNING_DIR, REFERENCES_DIR, KEYFRAMES_DIR, PROMPTS_DIR,
    RAW_DIR, NORMALIZED_DIR, FINAL_DIR, REPORTS_DIR,
    init_multishot_project, resolve_path, write_json_atomic, read_json_atomic,
    init_run_manifest, load_run_manifest, update_shot_status,
    set_project_status, sha256_of_dict, generate_stable_project_id,
    _validate_id, _safe_shot_filename,
)


class TestPathSafety:
    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_id("", "test")

    def test_abs_path_injected_id_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            _validate_id("/etc/passwd", "test")

    def test_traversal_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            _validate_id("../escape", "test")

    def test_newline_injection_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            _validate_id("shot\ninjected", "test")

    def test_safe_ids_pass(self):
        _validate_id("shot_001", "shot_id")
        _validate_id("p_test-project", "project_id")


class TestInitProject:
    def test_new_project_produces_required_folders(self, tmp_path):
        project_dir = init_multishot_project(
            "proj-test-001", title="Test Project", pipeline_dir=tmp_path
        )
        assert project_dir.exists()
        for subdir in (
            "artifacts", "assets/images", "assets/video", "assets/audio",
            "assets/music", "renders",
            PLANNING_DIR, REFERENCES_DIR, KEYFRAMES_DIR, PROMPTS_DIR,
            RAW_DIR, NORMALIZED_DIR, FINAL_DIR, REPORTS_DIR,
        ):
            assert (project_dir / subdir).is_dir(), f"missing {subdir}"

    def test_existing_project_preserved(self, tmp_path):
        init_multishot_project("proj-existing", title="Original", pipeline_dir=tmp_path)
        first = tmp_path / "proj-existing" / PLANNING_DIR
        first.mkdir(parents=True, exist_ok=True)
        (first / "pre-existing.json").write_text(json.dumps({"old": True}), encoding="utf-8")

        init_multishot_project("proj-existing", title="Original", pipeline_dir=tmp_path)
        assert (first / "pre-existing.json").read_text(encoding="utf-8") == '{"old": true}'

    def test_unsafe_project_id_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="unsafe"):
            init_multishot_project("../../escape", title="bad", pipeline_dir=tmp_path)


class TestResolvePath:
    def test_basic_category(self, tmp_path):
        project_dir = init_multishot_project("proj-path", title="Path Test", pipeline_dir=tmp_path)
        p = resolve_path(project_dir, PLANNING_DIR)
        assert p == project_dir / PLANNING_DIR

    def test_shot_id_appended(self, tmp_path):
        project_dir = init_multishot_project("proj-path", title="Path Test", pipeline_dir=tmp_path)
        p = resolve_path(project_dir, RAW_DIR, shot_id="shot_001", ext=".mp4")
        assert p.name == "shot_001.mp4"
        assert str(p).startswith(str(project_dir / RAW_DIR))

    def test_category_not_in_project_dir_rejected(self, tmp_path):
        project_dir = init_multishot_project("proj-path", title="Path Test", pipeline_dir=tmp_path)
        with pytest.raises(ValueError):
            resolve_path(project_dir, "planning/../../../etc", shot_id="shot_001")

    def test_invalid_category_rejected(self, tmp_path):
        project_dir = init_multishot_project("proj-path", title="Path Test", pipeline_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid category"):
            resolve_path(project_dir, "nonexistent")


class TestAtomicPersistence:
    def test_write_read_roundtrip(self, tmp_path):
        target = tmp_path / "a.json"
        data = {"key": "value", "nested": [1, 2, 3]}
        write_json_atomic(target, data)
        loaded = read_json_atomic(target)
        assert loaded == data

    def test_replaces_existing(self, tmp_path):
        target = tmp_path / "a.json"
        write_json_atomic(target, {"v": 1})
        write_json_atomic(target, {"v": 2})
        assert read_json_atomic(target) == {"v": 2}


class TestRunManifest:
    def test_init_creates_manifest(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        manifest = init_run_manifest(project_dir, shot_count=3)
        assert manifest["project_status"] == "CREATED"
        assert manifest["shot_count"] == 3
        assert manifest["shots"] == {}

    def test_load_reuses_existing(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        m1 = init_run_manifest(project_dir, shot_count=3)
        m2 = load_run_manifest(project_dir)
        assert m1 == m2
        assert m2["shot_count"] == 3

    def test_update_shot_status_persists(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        manifest = init_run_manifest(project_dir, shot_count=2)
        updated = update_shot_status(manifest, "shot_001", project_dir=project_dir,
                                      status="RUNNING", input_hash="abc123")
        assert updated["shots"]["shot_001"]["status"] == "RUNNING"
        assert updated["shots"]["shot_001"]["input_hash"] == "abc123"
        reloaded = load_run_manifest(project_dir)
        assert reloaded["shots"]["shot_001"]["status"] == "RUNNING"

    def test_set_project_status_validates_enum(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        manifest = init_run_manifest(project_dir, shot_count=2)
        updated = set_project_status(manifest, project_dir, "PLANNED")
        assert updated["project_status"] == "PLANNED"

    def test_set_project_status_rejects_invalid(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        manifest = init_run_manifest(project_dir, shot_count=2)
        with pytest.raises(ValueError, match="Invalid project_status"):
            set_project_status(manifest, project_dir, "NOT_A_STATUS")

    def test_mutate_requires_status_match(self, tmp_path):
        project_dir = init_multishot_project("proj-manifest", title="Manifest Test", pipeline_dir=tmp_path)
        manifest = init_run_manifest(project_dir, shot_count=2)
        with pytest.raises(ValueError, match="Cannot mutate"):
            update_shot_status(manifest, "shot_001", project_dir=project_dir,
                               status="RUNNING", required_status="COMPLETED")


class TestHelpers:
    def test_sha256_deterministic(self):
        obj = {"a": 1, "b": 2}
        h1 = sha256_of_dict(obj)
        h2 = sha256_of_dict(obj)
        assert h1 == h2
        assert len(h1) == 64

    def test_sha256_different_objects_differ(self):
        h1 = sha256_of_dict({"a": 1})
        h2 = sha256_of_dict({"a": 2})
        assert h1 != h2

    def test_generate_stable_project_id(self):
        id1 = generate_stable_project_id("same topic")
        id2 = generate_stable_project_id("same topic")
        assert id1 == id2
        id3 = generate_stable_project_id("different topic")
        assert id3 != id1

    def test_safe_shot_filename(self):
        name = _safe_shot_filename("shot", "shot_001", ext=".mp4")
        assert name == "shot_shot_001.mp4"

    def test_safe_shot_filename_rejects_traversal(self):
        with pytest.raises(ValueError, match="unsafe"):
            _safe_shot_filename("shot", "shot/../escape", ext=".mp4")
