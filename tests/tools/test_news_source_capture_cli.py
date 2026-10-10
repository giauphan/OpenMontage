"""CLI integration for pending news-source capture; no network access."""

import json
from pathlib import Path

import pytest

from lib.news_source_capture import (
    CaptureError,
    CapturePersistenceError,
    capture_source as library_capture_source,
)
from tools.news import news_pipeline_cli


URL = "https://news.example/story?token=do-not-log"


def _capture_with_fake_transport(project_dir, url, allowed_hosts):
    def transport(request_url, host):
        assert request_url == "https://news.example/story?token=do-not-log"
        assert host == "news.example"
        return (
            200,
            {"content-type": "text/html; charset=utf-8"},
            b"<html><head><title>Example story</title></head><body>Article text</body></html>",
            None,
        )

    return library_capture_source(
        project_dir, url, allowed_hosts, _transport=transport
    )


def test_capture_source_parser_entrypoint_writes_pending_provenance_only(
    tmp_path, monkeypatch, capsys
):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    artifacts = project_dir / "artifacts"
    artifacts.mkdir()
    evidence = artifacts / "evidence.json"
    checkpoint = project_dir / "checkpoint.json"
    evidence.write_text('{"canonical":"evidence"}\n', encoding="utf-8")
    checkpoint.write_text('{"canonical":"checkpoint"}\n', encoding="utf-8")
    before = (evidence.read_bytes(), checkpoint.read_bytes())

    monkeypatch.setattr(news_pipeline_cli, "capture_source", _capture_with_fake_transport)
    result = news_pipeline_cli.main([
        "capture-source", "--project-dir", str(project_dir), "--url", URL,
        "--allowed-host", "news.example",
    ])

    output = capsys.readouterr()
    record = json.loads(output.out)
    assert result == 0
    assert output.err == ""
    assert record["status"] == "pending_editorial_review"
    assert record["review_status"] == "pending"
    assert record["original_url"] == URL
    assert record["raw_sha256"] and record["extracted_sha256"]
    capture_dir = project_dir / "artifacts" / "news_source_capture"
    assert (capture_dir / record["provenance_file"]).is_file()
    assert (capture_dir / record["raw_file"]).is_file()
    assert (capture_dir / record["extracted_file"]).is_file()
    assert (evidence.read_bytes(), checkpoint.read_bytes()) == before


def test_capture_source_requires_all_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        news_pipeline_cli.main(["capture-source"])
    assert exc.value.code == 2
    assert "--project-dir" in capsys.readouterr().err


@pytest.mark.parametrize("directory_kind", ["missing", "file", "symlink"])
def test_capture_source_requires_existing_directory(tmp_path, directory_kind, capsys):
    project_dir = tmp_path / "project"
    if directory_kind == "file":
        project_dir.write_text("not a project directory", encoding="utf-8")
    elif directory_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        project_dir.symlink_to(target, target_is_directory=True)

    result = news_pipeline_cli.main([
        "capture-source", "--project-dir", str(project_dir), "--url", URL,
        "--allowed-host", "news.example",
    ])
    output = capsys.readouterr()
    assert result == 1
    assert "existing directory" in output.err
    assert "token=do-not-log" not in output.out + output.err


def test_capture_source_error_is_nonzero_and_does_not_log_url(monkeypatch, tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def fail(*args):
        raise CaptureError("source is unavailable")

    monkeypatch.setattr(news_pipeline_cli, "capture_source", fail)
    result = news_pipeline_cli.main([
        "capture-source", "--project-dir", str(project_dir), "--url", URL,
        "--allowed-host", "news.example",
    ])
    output = capsys.readouterr()
    assert result == 1
    assert "source is unavailable" in output.err
    assert "token=do-not-log" not in output.out + output.err


def test_capture_source_reports_retained_partial_artifacts(monkeypatch, tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def fail(*args):
        raise CapturePersistenceError("persistence incomplete", ["retained.raw"])

    monkeypatch.setattr(news_pipeline_cli, "capture_source", fail)
    result = news_pipeline_cli.main([
        "capture-source", "--project-dir", str(project_dir), "--url", URL,
        "--allowed-host", "news.example",
    ])
    output = capsys.readouterr()
    diagnostic = json.loads(output.err)
    assert result == 1
    assert diagnostic == {
        "status": "capture_persistence_failed",
        "error": "persistence incomplete",
        "partial_artifacts": ["retained.raw"],
    }
    assert "token=do-not-log" not in output.out + output.err
