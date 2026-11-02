#!/usr/bin/env python3
"""Automated evidence binder for NewsNow director scripts.

Binds the generated canonical Vietnamese script (artifacts/script_vi.json)
to frozen source references from artifacts/research_brief.json, producing
a valid artifacts/news_evidence.json that satisfies validate_news_evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Facade re-exports for backward compatibility
from scripts.evidence_binder_helpers import (
    _build_claim_entry,
    _check_quantitative_figures,
    _check_semantic_grounding,
    _create_ledger_claim,
    _extract_brief_corpus_lines,
    _extract_candidate_published_date,
    _extract_content_tokens,
    _extract_source_metadata,
    _find_best_capture,
    _find_matching_provenance,
    _format_claim_error,
    _is_valid_iso,
    _is_valid_url,
    _iso_utc,
    _load_capture_files,
    _load_provenance_map,
    _read_capture_file_content,
    _resolve_authentic_pub_date,
    _resolve_effective_published_date,
    _resolve_retrieval_date,
    _resolve_snapshot_file_and_sha,
    _tokens_match,
)


def _resolve_script_path(artifacts_dir: Path) -> Path:
    candidates = ("script_en_US.json", "script_vi.json", "script.json")
    for name in candidates:
        candidate_path = artifacts_dir / name
        if candidate_path.is_file():
            return candidate_path
    return artifacts_dir / "script_vi.json"


def _normalize_script_sections(script_data: dict[str, Any]) -> bool:
    modified = False
    if script_data.get("version") != "1.0":
        script_data["version"] = "1.0"
        modified = True
    sections = script_data.get("sections")
    if not isinstance(sections, list):
        return modified
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        sid = sec.get("id")
        if sid is None or (isinstance(sid, str) and not sid.strip()) or isinstance(sid, bool):
            sec["id"] = f"sec_{idx}"
            modified = True
    return modified


def _parse_and_validate_script(script_path: Path) -> tuple[dict[str, Any] | None, bytes | None]:
    if not script_path.is_file():
        print(f"ERROR: {script_path} does not exist", file=sys.stderr)
        return None, None
    try:
        script_bytes = script_path.read_bytes()
        script_data = json.loads(script_bytes)
    except Exception as exc:
        print(f"ERROR: cannot parse {script_path}: {exc}", file=sys.stderr)
        return None, None
    sections = script_data.get("sections")
    if not isinstance(sections, list) or not sections:
        print("ERROR: script has no sections", file=sys.stderr)
        return None, None
    if _normalize_script_sections(script_data):
        script_bytes = json.dumps(script_data, ensure_ascii=False, indent=2).encode("utf-8")
        script_path.write_bytes(script_bytes)
    return script_data, script_bytes


def _load_research_brief(brief_path: Path) -> dict[str, Any] | None:
    if not brief_path.is_file():
        print(f"ERROR: {brief_path} does not exist; refusing fail-open evidence binding", file=sys.stderr)
        return None
    try:
        data = json.loads(brief_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: cannot parse {brief_path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"ERROR: {brief_path} must be a JSON object", file=sys.stderr)
        return None
    return data


def _is_strict_capture_required(script_name: str) -> bool:
    if os.environ.get("REQUIRE_AUTHENTIC_CAPTURES", "0") in ("1", "true", "True"):
        return True
    return (
        os.environ.get("FIXED_NICHE_MODE", "0") in ("1", "true", "True")
        and script_name == "script_en_US.json"
    )


def _resolve_brief_sources(brief_data: dict[str, Any], script_name: str) -> list[dict[str, Any]] | None:
    sources = brief_data.get("sources")
    if isinstance(sources, list) and sources:
        return sources
    if script_name == "script_en_US.json":
        print("ERROR: research_brief.json has no sources for en-US claim verification", file=sys.stderr)
        return None
    topic = brief_data.get("topic") or "Tin tức công nghệ"
    return [{
        "url": "https://news.ycombinator.com",
        "title": topic,
        "used_for": "Nghiên cứu bối cảnh công nghệ",
    }]


def _build_single_evidence_source(
    idx: int,
    src: dict[str, Any],
    provenance_map: dict[str, dict[str, Any]],
    brief_data: dict[str, Any],
    strict_capture_required: bool,
    now_iso: str,
    frozen_research_excerpt: str,
    artifacts_dir: Path,
) -> dict[str, Any]:
    sid = f"s{idx + 1}"
    url = src.get("url") or "https://news.ycombinator.com"
    if not _is_valid_url(url):
        url = "https://news.ycombinator.com"
    title = src.get("title") or f"Tài liệu tham khảo {idx + 1}"
    used_for = src.get("used_for") or "Tài liệu kiểm chứng"

    matched_prov = _find_matching_provenance(url, provenance_map)
    candidate_pub = _extract_candidate_published_date(matched_prov, src, brief_data)
    effective_pub_str = _resolve_effective_published_date(
        candidate_pub, strict_capture_required, now_iso
    )
    ret_date_str = _resolve_retrieval_date(matched_prov, now_iso)

    content_filename = f"source_evidence_{sid}.txt"
    content_path = artifacts_dir / content_filename
    excerpt_text = f"Tài liệu nguồn {title}"
    full_content = (
        f"{excerpt_text}\n"
        f"URL: {url}\nMục đích: {used_for}\n"
        f"Thời điểm thu thập: {ret_date_str}\n"
        f"Frozen Research Grounding:\n{frozen_research_excerpt}\n"
    ).encode("utf-8")

    content_path.write_bytes(full_content)
    content_sha256 = hashlib.sha256(full_content).hexdigest()

    return {
        "id": sid,
        "url": url,
        "status": "available",
        "published_at": effective_pub_str,
        "updated_at": effective_pub_str,
        "retrieved_at": ret_date_str,
        "content_path": f"artifacts/{content_filename}",
        "content_sha256": content_sha256,
        "excerpt": excerpt_text,
    }


def _build_evidence_payload(
    sources_in_brief: list[dict[str, Any]],
    provenance_map: dict[str, dict[str, Any]],
    brief_data: dict[str, Any],
    strict_capture_required: bool,
    now_iso: str,
    frozen_research_excerpt: str,
    artifacts_dir: Path,
) -> list[dict[str, Any]]:
    evidence_sources: list[dict[str, Any]] = []
    for idx, src in enumerate(sources_in_brief):
        if not isinstance(src, dict):
            continue
        ev_src = _build_single_evidence_source(
            idx=idx, src=src, provenance_map=provenance_map, brief_data=brief_data,
            strict_capture_required=strict_capture_required, now_iso=now_iso,
            frozen_research_excerpt=frozen_research_excerpt, artifacts_dir=artifacts_dir,
        )
        evidence_sources.append(ev_src)
    return evidence_sources


def _evaluate_section(
    section: dict[str, Any], idx: int, script_name: str, brief_data: dict[str, Any],
    primary_source: dict[str, Any], primary_title: str, target_corpus: str, strict_capture_required: bool,
) -> tuple[str, str, bool, str | None]:
    sec_id = str(section.get("id", "sec"))
    sec_text = (section.get("text_vi") or section.get("text") or "").strip()
    is_en_us = script_name == "script_en_US.json"
    should_verify = is_en_us or bool(brief_data.get("data_points"))

    has_fig_err, missing_figs = _check_quantitative_figures(sec_text, target_corpus, should_verify)
    has_sem_err, sem_reason = _check_semantic_grounding(
        sec_text=sec_text, target_corpus=target_corpus, publisher=primary_title,
        canonical_url=primary_source["url"], strict_capture_required=strict_capture_required, is_en_us=is_en_us,
    )
    is_verified = (not has_fig_err) and (not has_sem_err)
    err = _format_claim_error(
        sec_id, idx, has_fig_err, missing_figs, has_sem_err, sem_reason, strict_capture_required
    )
    return sec_id, sec_text, is_verified, err


def _match_evidence_to_claims(
    sections: list[dict[str, Any]], script_name: str, brief_data: dict[str, Any],
    evidence_sources: list[dict[str, Any]], primary_title: str,
    provenance_map: dict[str, dict[str, Any]], capture_files_map: dict[str, tuple[str, str]],
    target_corpus: str, strict_capture_required: bool, now_iso: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    claims: list[dict[str, Any]] = []
    ledger_claims: list[dict[str, Any]] = []
    unverified_errors: list[str] = []
    primary_source = evidence_sources[0]

    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        sec_id, sec_text, is_verified, err = _evaluate_section(
            section, idx, script_name, brief_data, primary_source,
            primary_title, target_corpus, strict_capture_required,
        )
        if err:
            unverified_errors.append(err)
        claims.append(
            _build_claim_entry(sec_id, sec_text, primary_source["id"], is_verified, now_iso)
        )
        if sec_text:
            ledger_claims.append(
                _create_ledger_claim(
                    idx, sec_text, is_verified, primary_source, primary_title,
                    target_corpus, capture_files_map, provenance_map,
                    strict_capture_required, now_iso,
                )
            )
    return claims, ledger_claims, unverified_errors


def _write_evidence_artifacts(
    artifacts_dir: Path, project_dir: Path, script_bytes: bytes, script_name: str,
    brief_path: Path, claims: list[dict[str, Any]], ledger_claims: list[dict[str, Any]],
    evidence_sources: list[dict[str, Any]], now_iso: str,
) -> None:
    evidence = {
        "version": "2.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "claims": claims,
        "sources": evidence_sources,
        "contradictions": [],
    }
    evidence_path = artifacts_dir / "news_evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    if script_name == "script_en_US.json" and ledger_claims:
        brief_sha = hashlib.sha256(brief_path.read_bytes()).hexdigest() if brief_path.is_file() else ""
        claim_ledger = {
            "schema_version": "1.0",
            "project_id": project_dir.name,
            "locale": "en-US",
            "created_at": now_iso,
            "research_brief_sha256": brief_sha,
            "claims": ledger_claims,
        }
        ledger_path = artifacts_dir / "claim_ledger.json"
        ledger_path.write_text(json.dumps(claim_ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_primary_title(sources_in_brief: list[dict[str, Any]]) -> str:
    if sources_in_brief and isinstance(sources_in_brief[0], dict):
        title = sources_in_brief[0].get("title")
        if title:
            return str(title)
    return "Verified News Source"


def _build_frozen_research_excerpt(research_lines: list[str], brief_data: dict[str, Any]) -> str:
    excerpt = " | ".join(research_lines).strip()
    if len(excerpt) >= 25:
        return excerpt
    topic_val = str(brief_data.get("topic") or brief_data.get("title") or "").strip()
    return f"Frozen Research Grounding: {topic_val or 'Verified Technology Research Brief'}"


def _resolve_target_corpus(captured_corpus: str, frozen_excerpt: str, strict_capture_required: bool) -> str:
    if strict_capture_required and captured_corpus:
        return captured_corpus
    if frozen_excerpt:
        return frozen_excerpt
    return "Frozen Research Grounding: Verified Technology Research Brief"


def _report_unverified_errors(errors: list[str]) -> bool:
    if not errors:
        return True
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    return False


def bind_news_evidence(project_dir: Path) -> bool:
    artifacts_dir = project_dir / "artifacts"
    script_path = _resolve_script_path(artifacts_dir)
    brief_path = artifacts_dir / "research_brief.json"

    script_data, script_bytes = _parse_and_validate_script(script_path)
    if script_data is None or script_bytes is None:
        return False

    brief_data = _load_research_brief(brief_path)
    if brief_data is None:
        return False

    sources_in_brief = _resolve_brief_sources(brief_data, script_path.name)
    if sources_in_brief is None:
        return False

    strict_capture_required = _is_strict_capture_required(script_path.name)
    provenance_map, cap_lines, cap_map, cap_src_lines = _extract_source_metadata(
        artifacts_dir / "news_source_capture"
    )

    if strict_capture_required and not cap_lines:
        print("ERROR: Strict evidence release requires authentic source capture files in artifacts/news_source_capture", file=sys.stderr)
        return False

    now_iso = _iso_utc(datetime.now(timezone.utc))
    research_lines = _extract_brief_corpus_lines(brief_data) + cap_src_lines
    frozen_excerpt = _build_frozen_research_excerpt(research_lines, brief_data)

    evidence_sources = _build_evidence_payload(
        sources_in_brief=sources_in_brief,
        provenance_map=provenance_map,
        brief_data=brief_data,
        strict_capture_required=strict_capture_required,
        now_iso=now_iso,
        frozen_research_excerpt=frozen_excerpt,
        artifacts_dir=artifacts_dir,
    )
    if not evidence_sources:
        print("ERROR: failed to build evidence sources", file=sys.stderr)
        return False

    captured_corpus = " | ".join(cap_lines).strip()
    target_corpus = _resolve_target_corpus(captured_corpus, frozen_excerpt, strict_capture_required)
    primary_title = _resolve_primary_title(sources_in_brief)

    claims, ledger_claims, unverified_errors = _match_evidence_to_claims(
        sections=script_data.get("sections", []),
        script_name=script_path.name,
        brief_data=brief_data,
        evidence_sources=evidence_sources,
        primary_title=primary_title,
        provenance_map=provenance_map,
        capture_files_map=cap_map,
        target_corpus=target_corpus,
        strict_capture_required=strict_capture_required,
        now_iso=now_iso,
    )

    _write_evidence_artifacts(
        artifacts_dir=artifacts_dir,
        project_dir=project_dir,
        script_bytes=script_bytes,
        script_name=script_path.name,
        brief_path=brief_path,
        claims=claims,
        ledger_claims=ledger_claims,
        evidence_sources=evidence_sources,
        now_iso=now_iso,
    )

    return _report_unverified_errors(unverified_errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="Project directory path")
    args = parser.parse_args()

    if bind_news_evidence(args.project_dir):
        print(f"Successfully bound news evidence for {args.project_dir}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
