"""Test-only writer for portable offline news-evidence fixtures.

This module creates explicitly fictional fixture artifacts. It is not a source
provider and must never be used to authorize production publication.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _aware_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _script_sections(script_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(script_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing script_vi.json is not readable JSON: {exc}") from exc
    sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(sections, list) or not sections:
        raise ValueError("existing script_vi.json must contain non-empty sections; refusing to replace it")
    seen_ids: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError(f"existing script section {index} must be an object; refusing to replace the script")
        section_id = section.get("id")
        text = section.get("text_vi")
        if not isinstance(text, str) or not text.strip():
            text = section.get("text")
        if (
            not isinstance(section_id, (str, int))
            or isinstance(section_id, bool)
            or not str(section_id).strip()
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError(f"existing script section {index} needs a non-empty id and text_vi/text")
        normalized_id = str(section_id)
        if normalized_id in seen_ids:
            raise ValueError(f"existing script section id {normalized_id!r} is duplicated")
        seen_ids.add(normalized_id)
    return sections


def _write_unique_frozen_source(directory: Path, content: bytes, stamp: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"news-evidence-fixture-{stamp.replace(':', '').replace('-', '')}"
    suffix = 0
    while True:
        name = f"{stem}-{suffix}.txt"
        path = directory / name
        try:
            with path.open("xb") as frozen_file:
                frozen_file.write(content)
            return path
        except FileExistsError:
            suffix += 1


def write_reviewed_news_evidence(project_dir: Path) -> None:
    """Write fictional, test-only evidence for the project's canonical script.

    Existing ``artifacts/script_vi.json`` bytes and all its sections are
    preserved. If absent, a minimal clearly labeled test script is created.
    The only pre-existing artifact this helper replaces is the explicitly
    test-owned ``artifacts/news_evidence.json``.
    """
    root = Path(project_dir)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    script_path = artifacts / "script_vi.json"
    if script_path.exists():
        sections = _script_sections(script_path)
        script_bytes = script_path.read_bytes()
    else:
        sections = [{
            "id": "test-fixture-1",
            "text_vi": "TEST ONLY: fictional script section for evidence-gate tests.",
        }]
        script_payload = {
            "version": "1.0",
            "title": "TEST ONLY — fictional evidence fixture",
            "total_duration_seconds": 1,
            "sections": sections,
        }
        script_bytes = json.dumps(script_payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        script_path.write_bytes(script_bytes)

    now = datetime.now(timezone.utc)
    timestamp = _aware_iso(now)
    frozen_content = (
        "TEST FIXTURE ONLY — FICTIONAL SOURCE; NOT A REAL REPORT OR EVIDENCE.\n"
        "This frozen text exists only to exercise local news evidence validation.\n"
    ).encode("utf-8")
    frozen_path = _write_unique_frozen_source(
        artifacts / "test-fixtures" / "news-evidence", frozen_content, timestamp
    )
    relative_content_path = frozen_path.relative_to(root).as_posix()
    source_id = "test-fixture-source"
    claim_records = []
    for section in sections:
        section_id = section["id"]
        claim_records.append({
            "section_id": section_id,
            "claim": f"TEST ONLY: provenance fixture for script section {section_id}; no factual assertion.",
            "classification": "reported_fact",
            "consequential": False,
            "source_ids": [source_id],
            "reviewer": "TEST-ONLY offline fixture attestation",
            "reviewed_at": timestamp,
            "review_status": "approved",
        })

    publication_time = now - timedelta(minutes=3)
    update_time = now - timedelta(minutes=2)
    retrieval_time = now - timedelta(minutes=1)
    evidence = {
        "version": "2.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "claims": claim_records,
        "sources": [{
            "id": source_id,
            "url": "https://example.test/news-evidence-fixture",
            "status": "available",
            "published_at": _aware_iso(publication_time),
            "updated_at": _aware_iso(update_time),
            "retrieved_at": _aware_iso(retrieval_time),
            "content_path": relative_content_path,
            "content_sha256": hashlib.sha256(frozen_content).hexdigest(),
            "excerpt": "TEST FIXTURE ONLY — FICTIONAL SOURCE; NOT A REAL REPORT OR EVIDENCE.",
        }],
        "contradictions": [],
    }
    (artifacts / "news_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
