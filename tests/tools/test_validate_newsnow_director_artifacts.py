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

    expected_payload = {
        "version": "1.0",
        "title": "T",
        "total_duration_seconds": 10.0,
        "sections": [{"id": "1", "text": "A", "start_seconds": 0.0, "end_seconds": 10.0}]
    }
    assert json.loads(promoted.read_text()) == expected_payload


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


def test_scripts_prevent_recursive_invocation():
    """Verify that the director wrapper shell scripts explicitly forbid recursive execution in system prompt."""
    root = Path(__file__).resolve().parents[2]

    scripts = [
        root / "scripts" / "run_daily_news_pipeline.sh",
        root / "scripts" / "run_directors_for_existing.sh"
    ]

    for script_path in scripts:
        content = script_path.read_text(encoding="utf-8")
        assert "DIRECTOR_SYSTEM_NOTE=" in content
        # It must explicitly prevent infinite loops
        assert "infinite loop" in content or "recursion" in content


def test_scripts_resolve_hyperframes_from_node_modules():
    """Verify that both scripts check node_modules/.bin/hyperframes as a fallback path."""
    root = Path(__file__).resolve().parents[2]

    scripts = [
        root / "scripts" / "run_daily_news_pipeline.sh",
        root / "scripts" / "run_directors_for_existing.sh"
    ]

    for script_path in scripts:
        content = script_path.read_text(encoding="utf-8")
        assert "node_modules/.bin/hyperframes" in content


def test_validator_normalizes_director_schema_variants(tmp_path):
    project_id = tmp_path.name
    nested_dir = tmp_path / project_id
    nested_dir.mkdir()
    checkpoint = nested_dir / "checkpoint_script.json"

    # Variant payload with none of the strict schema names
    variant_payload = {
        "project_id": "cand_3eb816",
        "version": "2.0",
        "title_vi": "Test title",
        "total_duration_secs": 90,
        "sections": [
            {
                "id": 1,
                "label": "Hook",
                "narration": "Hello world",
                "duration_seconds": 10,
                "audio_file": "s1.wav",
                "scene_type": "hook"
            }
        ]
    }

    checkpoint.write_text(json.dumps({"artifacts": {"script": variant_payload}}))
    assert helper.validate_and_promote_director_artifacts(tmp_path) is True
    
    promoted = tmp_path / "artifacts" / "script_vi.json"
    assert promoted.is_file()
    data = json.loads(promoted.read_text())
    
    # Assert normalized values match schema
    assert data["version"] == "1.0"
    assert data["title"] == "Test title"
    assert data["total_duration_seconds"] == 90.0
    assert "project_id" not in data # Extraneous root key removed
    
    sec = data["sections"][0]
    assert sec["text"] == "Hello world"
    assert sec["start_seconds"] == 0.0
    assert sec["end_seconds"] == 10.0
    assert "scene_type" not in sec # Extraneous section key removed
    assert "narration" not in sec
