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
    _validate_id, _safe_shot_filename, mutate_run_manifest, write_artifact,
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
            "assets/music", "renders", "history",
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


@pytest.mark.parametrize("identifier", [".", "..", "C:drive", "CON", "x.", "a b"])
def test_unsafe_ids(identifier):
    with pytest.raises(ValueError, match="unsafe"):
        _validate_id(identifier)


def test_existing_directory_gets_canonical_marker(tmp_path):
    (tmp_path / "partial").mkdir()
    project = init_multishot_project("partial", title="Recovered", pipeline_dir=tmp_path)
    assert json.loads((project / "project.json").read_text())["pipeline_type"] == "multi-shot"
    assert (project / "history").is_dir()


def test_symlink_prefix_escape_rejected(tmp_path):
    project = init_multishot_project("safe", title="Safe", pipeline_dir=tmp_path)
    sibling = tmp_path / "safe-other"
    sibling.mkdir()
    (project / RAW_DIR).rmdir()
    (project / RAW_DIR).symlink_to(sibling, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        resolve_path(project, RAW_DIR, "shot_001", ".mp4")


def test_stale_same_project_snapshot_cannot_overwrite(tmp_path):
    project = init_multishot_project("cas", title="CAS", pipeline_dir=tmp_path)
    original = init_run_manifest(project, 2)
    stale = load_run_manifest(project)
    update_shot_status(original, "shot_001", project_dir=project, status="RUNNING")
    with pytest.raises(ValueError, match="Stale"):
        update_shot_status(stale, "shot_002", project_dir=project, status="RUNNING")
    assert load_run_manifest(project)["revision"] == 1
    assert set(load_run_manifest(project)["shots"]) == {"shot_001"}


def test_failed_mutation_preserves_memory_and_disk(tmp_path):
    import copy
    project = init_multishot_project("cas", title="CAS", pipeline_dir=tmp_path)
    manifest = init_run_manifest(project, 2)
    before = copy.deepcopy(manifest)
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        update_shot_status(manifest, "shot_001", project_dir=project, status="INVALID")
    assert manifest == before == load_run_manifest(project)


def test_concurrent_mutations_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    project = init_multishot_project("cas", title="CAS", pipeline_dir=tmp_path)
    init_run_manifest(project, 2)
    barrier = Barrier(2)

    def update(shot_id):
        snapshot = load_run_manifest(project)
        barrier.wait(timeout=5)
        try:
            update_shot_status(snapshot, shot_id, project_dir=project, status="RUNNING")
            return True
        except ValueError as exc:
            assert "Stale" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["shot_001", "shot_002"]))
    assert sorted(results) == [False, True]
    assert load_run_manifest(project)["revision"] == 1


def test_supporting_records_validate_at_persistence_boundary(tmp_path):
    import jsonschema
    project = init_multishot_project("records", title="Records", pipeline_dir=tmp_path)
    from lib.multishot_schemas import MultishotValidationError
    with pytest.raises(MultishotValidationError):
        write_json_atomic(project / PLANNING_DIR / "request.json", {})
    with pytest.raises(ValueError, match="Unknown artifact"):
        write_artifact(project, "requset", {})
    path = project / REPORTS_DIR / "run_manifest.json"
    path.write_text('{}')
    with pytest.raises(jsonschema.ValidationError):
        load_run_manifest(project)


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
