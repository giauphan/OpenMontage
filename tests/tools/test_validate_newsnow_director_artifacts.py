"""Detailed tests for validate_newsnow_director_artifacts boundary helper."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.validate_newsnow_director_artifacts as helper


def test_validator_rejects_missing_directory(tmp_path):
    assert helper.validate_and_promote_director_artifacts(tmp_path / "missing") is False


def test_validator_accepts_valid_flat_artifact(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    script = arts / "script_vi.json"

    # Schema invalid (missing version)
    script.write_text(json.dumps({"title": "T", "total_duration_seconds": 10, "sections": [{"id": "1", "text": "A", "start_seconds": 0, "end_seconds": 10}]}))
    assert helper.validate_and_promote_director_artifacts(tmp_path) is False

    # Valid
    script.write_text(json.dumps({"version": "1.0", "title": "T", "total_duration_seconds": 10, "sections": [{"id": "1", "text_vi": "A", "text": "E", "start_seconds": 0, "end_seconds": 10}]}))
    assert helper.validate_and_promote_director_artifacts(tmp_path) is True


def test_validator_promotes_nested_checkpoint(tmp_path):
    project_id = tmp_path.name
    nested_dir = tmp_path / project_id
    nested_dir.mkdir()
    checkpoint = nested_dir / "checkpoint_script.json"

    payload = {
        "version": "1.0",
        "title": "T",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text_vi": "A", "start_seconds": 0, "end_seconds": 10}]
    }

    # Stale/old checkpoint check
    import os
    checkpoint.write_text(json.dumps({"artifacts": {"script": payload}}))
    st = checkpoint.stat()
    assert helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=st.st_mtime_ns + 1000000000) is False

    # Fresh checkpoint
    assert helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=st.st_mtime_ns - 1000000000) is True

    # Promoted successfully
    promoted = tmp_path / "artifacts" / "script_vi.json"
    assert promoted.is_file()
    assert json.loads(promoted.read_text()) == payload


def test_cli_integration(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    (arts / "script_vi.json").write_text(json.dumps({
        "version": "1.0",
        "title": "T",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text_vi": "A", "start_seconds": 0, "end_seconds": 10}]
    }))

    env = {"PYTHONPATH": str(Path(helper.__file__).resolve().parents[1])}
    res = subprocess.run([sys.executable, str(helper.__file__), str(tmp_path)], env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert "✓ Validated" in res.stdout
