import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.force_publish_clear_uniqueness import clear_uniqueness_for_project


def test_clear_uniqueness_missing_metadata(tmp_path, monkeypatch):
    """Return False when publish_metadata.json does not exist."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "test_proj").mkdir(parents=True)

    mock_store = MagicMock()
    result = clear_uniqueness_for_project(mock_store, "test_proj")
    assert result is False


def test_clear_uniqueness_missing_asset(tmp_path, monkeypatch):
    """Return False when referenced asset_path file does not exist."""
    monkeypatch.chdir(tmp_path)
    project_dir = tmp_path / "projects" / "test_proj"
    project_dir.mkdir(parents=True)
    meta = {
        "id": "cand_123",
        "title": "Test Title",
        "asset_path": "renders/final_full.mp4",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(meta))

    mock_store = MagicMock()
    result = clear_uniqueness_for_project(mock_store, "test_proj")
    assert result is False


def test_clear_uniqueness_clears_records(tmp_path, monkeypatch):
    """Return True and delete records when project files and records exist."""
    monkeypatch.chdir(tmp_path)
    project_dir = tmp_path / "projects" / "test_proj"
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True)
    asset_file = renders_dir / "final_full.mp4"
    asset_file.write_bytes(b"dummy video content")

    meta = {
        "id": "cand_123",
        "title": "Test Title",
        "asset_path": "renders/final_full.mp4",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(meta))

    mock_store = MagicMock()
    mock_store.get.return_value = {"existing": "record"}
    mock_store._url.side_effect = lambda k: f"http://firestore/{k}"

    with patch("scripts.force_publish_clear_uniqueness.file_sha256", return_value="sha123"), \
         patch("scripts.force_publish_clear_uniqueness.media_fingerprint", return_value="vis123"):
        result = clear_uniqueness_for_project(mock_store, "test_proj")

    assert result is True
    assert mock_store.session.delete.call_count == 6


def test_clear_uniqueness_delete_failure(tmp_path, monkeypatch):
    """Return False when store.session.delete raises an exception."""
    monkeypatch.chdir(tmp_path)
    project_dir = tmp_path / "projects" / "test_proj"
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True)
    asset_file = renders_dir / "final_full.mp4"
    asset_file.write_bytes(b"dummy video content")

    meta = {
        "id": "cand_123",
        "title": "Test Title",
        "asset_path": "renders/final_full.mp4",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(meta))

    mock_store = MagicMock()
    mock_store.get.return_value = {"existing": "record"}
    mock_store.session.delete.side_effect = Exception("Firestore API network error")

    with patch("scripts.force_publish_clear_uniqueness.file_sha256", return_value="sha123"), \
         patch("scripts.force_publish_clear_uniqueness.media_fingerprint", return_value="vis123"):
        result = clear_uniqueness_for_project(mock_store, "test_proj")

    assert result is False
