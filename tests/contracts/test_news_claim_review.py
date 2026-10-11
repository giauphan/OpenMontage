"""Contract tests for the isolated pending claim-review worksheet."""

import hashlib
import json
import os
from pathlib import Path

import pytest

import lib.news_claim_review as news_claim_review
import lib.news_source_capture as news_source_capture
from lib.news_claim_review import (
    ReviewWorksheetError,
    ReviewWorksheetPersistenceError,
    prepare_claim_review,
)


def _fixture(tmp_path: Path):
    project = tmp_path / "project"
    capture_dir = project / "artifacts/news_source_capture"
    capture_dir.mkdir(parents=True)
    script = {"sections": [
        {"id": 1, "text_vi": "Original full-script section wording."},
        {"id": "2", "text": "Second exact section wording."},
    ]}
    script_path = project / "artifacts/script_vi.json"
    script_bytes = json.dumps(script, ensure_ascii=False).encode()
    script_path.write_bytes(script_bytes)
    # A separate reels artifact is deliberately outside this full-script API.
    (project / "artifacts/script_reels.json").write_text(
        json.dumps({"sections": [{"id": "r1", "text": "Different reels wording."}]}),
        encoding="utf-8",
    )
    paths = []
    for revision in ("rev-a", "rev-b"):
        raw_name = f"{revision}.raw"
        extracted_name = f"{revision}.extracted.json"
        text = "Untrusted page text. A suggested quotation."
        raw = b"<html>Untrusted page text.</html>"
        extracted = {"text": text, "published_at": None, "updated_at": None}
        extracted_bytes = (json.dumps(extracted, sort_keys=True, indent=2) + "\n").encode()
        (capture_dir / raw_name).write_bytes(raw)
        (capture_dir / extracted_name).write_bytes(extracted_bytes)
        provenance = {
            "version": "1.0", "capture_id": revision,
            "status": "pending_editorial_review", "review_status": "pending",
            "capture_dir": "artifacts/news_source_capture",
            "raw_file": raw_name, "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "extracted_file": extracted_name,
            "extracted_sha256": hashlib.sha256(extracted_bytes).hexdigest(),
            "provenance_file": f"{revision}.provenance.json",
            "original_url": "https://publisher.test/a", "final_url": "https://publisher.test/a",
            "redirect_chain": ["https://publisher.test/a"], "content_type": "text/html",
            "published_at": None, "updated_at": None, "retrieved_at": "2026-10-10T10:00:00Z",
            "excerpt": "A suggested quotation.",
            "rights_attribution_notes": "Not assessed by capture; editorial review required.",
        }
        provenance_path = capture_dir / f"{revision}.provenance.json"
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        provenance_hash = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
        paths.append((provenance_path.relative_to(project), provenance_hash))
    return project, script_bytes, paths


def test_creates_pending_full_script_scaffold_bound_to_selected_revisions(tmp_path):
    project, script_bytes, paths = _fixture(tmp_path)
    worksheet = prepare_claim_review(project, [paths[0]])
    assert worksheet["status"] == "pending_editorial_review"
    assert worksheet["rendition_scope"] == "full"
    assert worksheet["script_sha256"] == hashlib.sha256(script_bytes).hexdigest()
    assert [section["script_wording"] for section in worksheet["sections"]] == [
        "Original full-script section wording.", "Second exact section wording."
    ]
    assert all(section["mapping_status"] == "unresolved" and not section["candidate_mappings"] for section in worksheet["sections"])
    assert worksheet["selected_captures"][0]["capture_id"] == "rev-a"
    assert worksheet["selected_captures"][0]["published_at"] is None
    assert worksheet["selected_captures"][0]["rights_status"] == "unresolved"
    assert worksheet["selected_captures"][0]["authority_status"] == "unresolved"
    assert worksheet["reviewer"] is None and worksheet["approval"] is None
    saved = project / worksheet["worksheet_file"]
    assert saved.is_file()
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == worksheet["worksheet_sha256"]
    original_script = project / "artifacts/script_vi.json"
    assert original_script.read_bytes() == script_bytes
    assert not (project / "artifacts/news_evidence.json").exists()


def _capture_with_test_transport(project):
    body = b"<html><head><title>Fixture report</title></head><body><p>Captured article text for an integration test.</p></body></html>"
    calls = []

    def transport(url, host):
        calls.append((url, host))
        return 200, {"content-type": "text/html; charset=utf-8"}, body, None

    record = news_source_capture.capture_source(
        project, "https://publisher.test/report", {"publisher.test"}, _transport=transport
    )
    provenance = project / "artifacts/news_source_capture" / record["provenance_file"]
    return record, provenance, hashlib.sha256(provenance.read_bytes()).hexdigest(), calls


def test_real_capture_to_cli_worksheet_integration_and_tamper_hold(tmp_path, monkeypatch, capsys):
    from tools.news import news_pipeline_cli

    project, script_bytes, _ = _fixture(tmp_path)
    record, provenance_path, provenance_sha, transport_calls = _capture_with_test_transport(project)
    assert transport_calls == [("https://publisher.test/report", "publisher.test")]
    capture_dir = provenance_path.parent
    capture_paths = [capture_dir / record[key] for key in ("raw_file", "extracted_file", "provenance_file")]
    capture_bytes = {path: path.read_bytes() for path in capture_paths}
    script_path = project / "artifacts/script_vi.json"

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("prepare-review must not perform network requests")

    def unexpected_director(*_args, **_kwargs):
        raise AssertionError("prepare-review must not call director selection")

    monkeypatch.setattr(news_source_capture, "_bounded_request", unexpected_network)
    monkeypatch.setattr(news_pipeline_cli.NewsSelector, "select_and_research", unexpected_director)
    args = [
        "prepare-review", "--project-dir", str(project), "--capture",
        f"{provenance_path.relative_to(project)}={provenance_sha}",
    ]
    assert news_pipeline_cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    worksheet_path = project / result["worksheet_file"]
    worksheet_bytes = worksheet_path.read_bytes()
    worksheet = json.loads(worksheet_bytes)
    assert hashlib.sha256(worksheet_bytes).hexdigest() == result["worksheet_sha256"]
    assert result["selected_captures"][0]["capture_id"] == record["capture_id"]
    assert worksheet["status"] == "pending_editorial_review"
    assert worksheet["approval"] is None and worksheet["reviewer"] is None
    assert script_path.read_bytes() == script_bytes
    assert all(path.read_bytes() == data for path, data in capture_bytes.items())
    assert not (project / "artifacts/news_evidence.json").exists()
    assert not (project / "checkpoints").exists()
    assert not list(project.rglob("*checkpoint*"))

    retained_before = worksheet_path.read_bytes()
    (capture_dir / record["raw_file"]).write_bytes(b"tampered after worksheet creation")
    assert news_pipeline_cli.main(args) == 1
    assert worksheet_path.read_bytes() == retained_before
    assert len(list((project / "artifacts/news_claim_review").glob("*.review-pending.json"))) == 1
    assert "SHA-256 mismatch" in capsys.readouterr().err


def test_rejects_redirect_chain_not_bound_to_capture_urls(tmp_path):
    project, _, paths = _fixture(tmp_path)
    provenance_path = project / paths[0][0]
    provenance = json.loads(provenance_path.read_text())
    provenance["redirect_chain"] = ["https://different.test/article"]
    provenance_path.write_text(json.dumps(provenance))
    pinned = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
    with pytest.raises(ReviewWorksheetError, match="consistent complete"):
        prepare_claim_review(project, [(paths[0][0], pinned)])


def test_revisions_are_unique_and_preserve_explicit_capture_selection(tmp_path):
    project, _, paths = _fixture(tmp_path)
    first = prepare_claim_review(project, [paths[0]])
    second = prepare_claim_review(project, [paths[1]])
    assert first["worksheet_file"] != second["worksheet_file"]
    assert first["selected_captures"][0]["capture_id"] == "rev-a"
    assert second["selected_captures"][0]["capture_id"] == "rev-b"
    assert (project / first["worksheet_file"]).exists()


@pytest.mark.parametrize("case", ["wrong-hash", "tampered-raw", "tampered-extraction", "malformed-provenance", "missing-capture", "symlink-capture"])
def test_rejects_invalid_or_tampered_capture_inputs(tmp_path, case):
    project, _, paths = _fixture(tmp_path)
    path, digest = paths[0]
    provenance = project / path
    if case == "wrong-hash":
        digest = "0" * 64
    elif case == "tampered-raw":
        (provenance.parent / "rev-a.raw").write_bytes(b"changed")
    elif case == "tampered-extraction":
        (provenance.parent / "rev-a.extracted.json").write_text('{"text":"changed"}')
    elif case == "malformed-provenance":
        provenance.write_text("{")
        digest = hashlib.sha256(provenance.read_bytes()).hexdigest()
    elif case == "missing-capture":
        provenance.unlink()
    elif case == "symlink-capture":
        raw = provenance.parent / "rev-a.raw"
        raw.unlink()
        raw.symlink_to(provenance.parent / "rev-b.raw")
    with pytest.raises(ReviewWorksheetError):
        prepare_claim_review(project, [(path, digest)])


def test_rejects_malformed_or_duplicate_script_sections(tmp_path):
    project, _, paths = _fixture(tmp_path)
    script_path = project / "artifacts/script_vi.json"
    script_path.write_text(json.dumps({"sections": [{"id": 1, "text": "x"}, {"id": 1, "text": "y"}]}))
    with pytest.raises(ReviewWorksheetError, match="unique"):
        prepare_claim_review(project, [paths[0]])


@pytest.mark.parametrize("bad_json", [b'{"sections":[],"sections":[]}', b'{"sections":[],"n":NaN}', b'{"sections":[],"n":Infinity}'])
def test_rejects_duplicate_keys_and_non_finite_json_constants(tmp_path, bad_json):
    project, _, paths = _fixture(tmp_path)
    (project / "artifacts/script_vi.json").write_bytes(bad_json)
    with pytest.raises(ReviewWorksheetError, match="malformed"):
        prepare_claim_review(project, [paths[0]])


@pytest.mark.parametrize("bad_extraction", [b'{"text":"x","text":"y"}', b'{"text":"x","score":NaN}'])
def test_rejects_duplicate_keys_and_constants_in_extraction(tmp_path, bad_extraction):
    project, _, paths = _fixture(tmp_path)
    capture_dir = project / "artifacts/news_source_capture"
    extracted_path = capture_dir / "rev-a.extracted.json"
    extracted_path.write_bytes(bad_extraction)
    provenance_path = project / paths[0][0]
    provenance = json.loads(provenance_path.read_text())
    provenance["extracted_sha256"] = hashlib.sha256(bad_extraction).hexdigest()
    provenance["excerpt"] = "x"
    provenance_path.write_text(json.dumps(provenance))
    pinned = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
    with pytest.raises(ReviewWorksheetError, match="malformed"):
        prepare_claim_review(project, [(paths[0][0], pinned)])


def test_rejects_duplicate_keys_in_pinned_provenance(tmp_path):
    project, _, paths = _fixture(tmp_path)
    provenance = project / paths[0][0]
    provenance.write_bytes(b'{"version":"1.0","version":"2.0"}')
    with pytest.raises(ReviewWorksheetError, match="malformed"):
        prepare_claim_review(project, [(paths[0][0], hashlib.sha256(provenance.read_bytes()).hexdigest())])


def test_rejects_non_string_digest_and_empty_raw_capture(tmp_path):
    project, _, paths = _fixture(tmp_path)
    from typing import cast

    with pytest.raises(ReviewWorksheetError, match="SHA-256 string"):
        prepare_claim_review(project, [(paths[0][0], cast(str, None))])
    raw = project / "artifacts/news_source_capture/rev-a.raw"
    raw.write_bytes(b"")
    with pytest.raises(ReviewWorksheetError, match="must not be empty"):
        prepare_claim_review(project, [paths[0]])


def test_bounded_read_rejects_oversized_script_without_unbounded_read(tmp_path, monkeypatch):
    project, _, paths = _fixture(tmp_path)
    (project / "artifacts/script_vi.json").write_bytes(b" " * 10000)
    monkeypatch.setattr(news_claim_review, "MAX_SCRIPT_BYTES", 31)
    original_read = os.read
    requested = []

    def tracked_read(fd, count):
        requested.append(count)
        return original_read(fd, count)

    monkeypatch.setattr(news_claim_review.os, "read", tracked_read)
    with pytest.raises(ReviewWorksheetError, match="exceeds size limit"):
        prepare_claim_review(project, [paths[0]])
    assert sum(requested) <= 32


def test_descriptor_walk_survives_directory_replacement_race(tmp_path, monkeypatch):
    project, script_bytes, _ = _fixture(tmp_path)
    root_fd = os.open(project, news_claim_review._DIR_FLAGS)
    original_open = os.open
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "script_vi.json").write_bytes(b'{"sections":[]}')
    swapped = False

    def racing_open(name, flags, *args, **kwargs):
        nonlocal swapped
        if name == "script_vi.json" and kwargs.get("dir_fd") is not None and not swapped:
            artifacts = project / "artifacts"
            held = project / "artifacts-held"
            artifacts.rename(held)
            artifacts.symlink_to(outside, target_is_directory=True)
            try:
                fd = original_open(name, flags, *args, **kwargs)
            finally:
                artifacts.unlink()
                held.rename(artifacts)
            swapped = True
            return fd
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(news_claim_review.os, "open", racing_open)
    try:
        data = news_claim_review._read_real(
            project / "artifacts/script_vi.json", project, root_fd,
            news_claim_review.MAX_SCRIPT_BYTES, [0],
        )
    finally:
        os.close(root_fd)
    assert swapped
    assert data == script_bytes


def test_reports_atomic_persistence_failure_and_cli_partial_artifacts(tmp_path, monkeypatch, capsys):
    project, _, paths = _fixture(tmp_path)
    real_fsync = os.fsync
    fail_once = True

    def fail_stage_fsync(fd):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("simulated fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(news_claim_review.os, "fsync", fail_stage_fsync)
    with pytest.raises(ReviewWorksheetPersistenceError) as error:
        prepare_claim_review(project, [paths[0]])
    partials = error.value.partial_artifacts
    assert len(partials) == 1 and Path(partials[0]).exists()
    assert not list((project / "artifacts/news_claim_review").glob("*.review-pending.json"))

    from argparse import Namespace
    from tools.news import news_pipeline_cli

    monkeypatch.setattr(news_pipeline_cli, "prepare_claim_review", lambda *_: (_ for _ in ()).throw(
        ReviewWorksheetPersistenceError("simulated", ["artifacts/news_claim_review/partial.tmp"])
    ))
    result = news_pipeline_cli.run_prepare_review(Namespace(capture=[f"{paths[0][0]}={paths[0][1]}"], project_dir=project))
    assert result == 1
    assert '"status": "worksheet_persistence_failed"' in capsys.readouterr().err


def test_rejects_symlink_script_and_escaping_input(tmp_path):
    project, _, paths = _fixture(tmp_path)
    script_path = project / "artifacts/script_vi.json"
    contents = script_path.read_bytes()
    script_path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(contents)
    script_path.symlink_to(outside)
    with pytest.raises(ReviewWorksheetError):
        prepare_claim_review(project, [paths[0]])
    script_path.unlink()
    script_path.write_bytes(contents)
    with pytest.raises(ReviewWorksheetError):
        prepare_claim_review(project, [(Path("../outside.json"), "0" * 64)])
