"""Contract tests exercise the offline news evidence validator with frozen fixtures."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.news_evidence import validate_news_evidence

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def frozen_project(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    source_content = b"TEST ONLY: fictional frozen source content; no real news fact is asserted.\n"
    (artifacts / "source-s1.txt").write_bytes(source_content)
    script = {"version": "1.0", "title": "Tin tuc", "sections": [
        {"id": "1", "text_vi": "TEST ONLY: fictional evidence-gate section one."},
        {"id": 2, "text_vi": "TEST ONLY: fictional evidence-gate section two."},
    ]}
    script_bytes = json.dumps(script, ensure_ascii=False, separators=(",", ":")).encode()
    (artifacts / "script_vi.json").write_bytes(script_bytes)
    evidence = {
        "version": "1.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "claims": [
            {"section_id": "1", "claim": "TEST ONLY: fictional provenance record for section one", "source_ids": ["s1"], "reviewer": "TEST-ONLY editor-1", "reviewed_at": "2026-10-09T11:30:00Z", "review_status": "approved"},
            {"section_id": 2, "claim": "TEST ONLY: fictional provenance record for section two", "source_ids": ["s1"], "reviewer": "TEST-ONLY editor-1", "reviewed_at": "2026-10-09T11:30:00Z", "review_status": "approved"},
        ],
        "sources": [{
            "id": "s1", "url": "https://publisher.example/report", "status": "available",
            "published_at": "2026-10-08T08:00:00Z", "updated_at": "2026-10-09T08:00:00+00:00",
            "retrieved_at": "2026-10-09T11:00:00Z", "content_path": "artifacts/source-s1.txt",
            "content_sha256": hashlib.sha256(source_content).hexdigest(),
            "excerpt": "TEST ONLY: fictional frozen source content",
        }],
        "contradictions": [],
    }
    (artifacts / "news_evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    return tmp_path


def evidence(project: Path) -> dict:
    path = project / "artifacts/news_evidence.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save(project: Path, payload: dict) -> None:
    (project / "artifacts/news_evidence.json").write_text(json.dumps(payload), encoding="utf-8")


def validate(project: Path, hours: float = 48) -> dict:
    return validate_news_evidence(project, hours, now=NOW)


def test_accepts_fresh_frozen_provenance_bound_to_complete_script(tmp_path):
    assert validate(frozen_project(tmp_path))["ok"] is True


@pytest.mark.parametrize("field,value", [
    ("updated_at", "2026-10-01T00:00:00Z"),
    ("updated_at", "2026-10-10T00:00:00Z"),
    ("published_at", "not-a-date"),
    ("retrieved_at", "2026-10-09T11:00:00"),
    ("retrieved_at", "2026-10-09T07:00:00Z"),
    ("updated_at", "2026-10-08T11:59:59.999999Z"),
])
def test_rejects_stale_future_invalid_and_timezone_naive_dates(tmp_path, field, value):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0][field] = value
    save(project, item)
    result = validate(project, 24)
    assert not result["ok"]


def test_accepts_source_at_exact_freshness_limit(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["updated_at"] = "2026-10-08T12:00:00Z"
    save(project, item)
    assert validate(project, 24)["ok"]


def test_rejects_source_just_beyond_freshness_limit(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["updated_at"] = "2026-10-08T11:59:59.999999Z"
    save(project, item)
    assert not validate(project, 24)["ok"]


def test_rejects_source_outage(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["status"] = "outage"
    save(project, item)
    assert not validate(project)["ok"]


def test_rejects_unresolved_contradiction_and_corrected_claim(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["contradictions"] = [{"claim": "42 units", "status": "unresolved"}]
    save(project, item)
    assert not validate(project)["ok"]


def test_rejects_script_mutation_even_when_evidence_is_unchanged(tmp_path):
    project = frozen_project(tmp_path)
    script_path = project / "artifacts/script_vi.json"
    script_path.write_bytes(script_path.read_bytes() + b" ")
    assert not validate(project)["ok"]


@pytest.mark.parametrize("path", ["../../outside.txt", "/tmp/outside.txt", "artifacts/missing.txt"])
def test_rejects_path_escape_absolute_and_missing_local_content(tmp_path, path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["content_path"] = path
    save(project, item)
    assert not validate(project)["ok"]


def test_rejects_content_hash_mismatch_and_nonmatching_excerpt(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["excerpt"] = "invented quote"
    save(project, item)
    assert not validate(project)["ok"]


def test_rejects_missing_section_claim_or_unreviewed_claim(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["claims"].pop()
    save(project, item)
    assert not validate(project)["ok"]
    item = evidence(project)
    item["claims"][0]["reviewer"] = ""
    save(project, item)
    assert not validate(project)["ok"]
    item = evidence(project)
    item["claims"][0]["reviewed_at"] = "2026-10-09T10:00:00Z"
    save(project, item)
    assert not validate(project)["ok"]


@pytest.mark.parametrize("status", ["pending", "rejected", None])
def test_claim_requires_explicit_approved_editorial_verdict(tmp_path, status):
    project = frozen_project(tmp_path)
    item = evidence(project)
    if status is None:
        item["claims"][0].pop("review_status", None)
    else:
        item["claims"][0]["review_status"] = status
    save(project, item)
    result = validate(project)
    assert not result["ok"]
    assert any("review_status" in error for error in result["errors"])


def test_rejects_missing_or_invented_source_reference(tmp_path):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["claims"][0]["source_ids"] = ["fabricated"]
    save(project, item)
    assert not validate(project)["ok"]


@pytest.mark.parametrize("limit", [0, -1, float("inf"), float("nan"), 721, 10 ** 400, True, "24"])
def test_rejects_invalid_freshness_limit_types_and_ranges(tmp_path, limit):
    project = frozen_project(tmp_path)
    assert not validate_news_evidence(project, limit, now=NOW)["ok"]


def test_rejects_malformed_json_and_wrong_evidence_types(tmp_path):
    project = frozen_project(tmp_path)
    (project / "artifacts/news_evidence.json").write_text("{", encoding="utf-8")
    assert not validate(project)["ok"]
    (project / "artifacts/news_evidence.json").write_text("[]", encoding="utf-8")
    assert not validate(project)["ok"]


@pytest.mark.parametrize("sections", [123, None, {}, [None], [{"id": " ", "text": "x"}], [{"id": "x", "text": 42}]])
def test_rejects_malformed_sections_and_missing_script_text(tmp_path, sections):
    project = frozen_project(tmp_path)
    script_path = project / "artifacts/script_vi.json"
    payload = json.loads(script_path.read_text(encoding="utf-8"))
    payload["sections"] = sections
    script_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not validate(project)["ok"]


@pytest.mark.parametrize("url", ["ftp://publisher.example/a", "http://[invalid", "https://host.example:99999/a"])
def test_rejects_invalid_or_non_http_source_urls(tmp_path, url):
    project = frozen_project(tmp_path)
    item = evidence(project)
    item["sources"][0]["url"] = url
    save(project, item)
    assert not validate(project)["ok"]


def test_rejects_invalid_utf8_frozen_content_without_raising(tmp_path):
    project = frozen_project(tmp_path)
    content_path = project / "artifacts/source-s1.txt"
    content_path.write_bytes(bytes([255, 254]))
    item = evidence(project)
    item["sources"][0]["content_sha256"] = hashlib.sha256(content_path.read_bytes()).hexdigest()
    item["sources"][0]["excerpt"] = chr(0xD800)
    save(project, item)
    result = validate(project)
    assert not result["ok"]
    assert result["errors"]


def test_cli_emits_json_failure_for_missing_or_malformed_arguments(tmp_path):
    cli = Path(__file__).resolve().parents[2] / "scripts/validate_news_evidence.py"
    for argv in ([], [str(tmp_path), "--max-source-age-hours", "not-a-number"]):
        completed = subprocess.run([sys.executable, str(cli), *argv], capture_output=True, text=True)
        assert completed.returncode != 0
        result = json.loads(completed.stdout)
        assert result["ok"] is False
        assert result["status"] == "failed"
        assert result["errors"]


def test_cli_returns_nonzero_json_for_invalid_project(tmp_path):
    cli = Path(__file__).resolve().parents[2] / "scripts/validate_news_evidence.py"
    completed = subprocess.run([
        sys.executable, str(cli), str(tmp_path / "missing"), "--max-source-age-hours", "24",
    ], capture_output=True, text=True)
    assert completed.returncode != 0
    result = json.loads(completed.stdout)
    assert result["ok"] is False
    assert result["errors"]


def test_missing_project_fails_closed(tmp_path):
    assert not validate(tmp_path / "absent")["ok"]
