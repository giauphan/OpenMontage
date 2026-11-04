#!/usr/bin/env python3
"""Helper functions for news evidence binding and verification.

Provides pure domain and parsing utilities for source extraction, token analysis,
date resolution, and factual grounding checks without global side effects.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_valid_iso(val: Any) -> bool:
    if not isinstance(val, str) or not val.strip():
        return False
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.tzinfo is not None
    except Exception:
        return False


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except Exception:
        return False


_STOPWORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "were", "about", "when", "where", "their",
    "there", "which", "would", "could", "should", "these", "those", "other", "into", "more",
    "some", "such", "than", "then", "them", "also", "only", "well", "even", "most", "what",
    "will", "your", "they", "each", "both", "across", "under", "after", "while", "during", "using",
    "over", "does", "many", "much", "very", "every", "first", "just", "chúng", "ta", "quý", "vị",
    "các", "những", "được", "trong", "cho", "với", "của", "là", "và", "có", "đến", "này", "đây",
    "theo", "một", "nhiều", "như",
})


def _extract_content_tokens(text: str) -> set[str]:
    pattern = r"[A-Za-z0-9àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]{3,}"
    return {w for w in re.findall(pattern, text.lower()) if w not in _STOPWORDS}


def _tokens_match(token: str, source_tokens: set[str]) -> bool:
    if token in source_tokens:
        return True
    if len(token) < 4:
        return False
    for st in source_tokens:
        if len(st) >= 4 and (token.startswith(st) or st.startswith(token)):
            return True
    return False


def _min_token_overlap(token_count: int) -> int:
    return 2 if token_count >= 4 else (1 if token_count >= 1 else 0)


def _dp_source_label(dp: dict[str, Any]) -> str:
    src = dp.get("source_name") or dp.get("source_url")
    return str(src).strip() if src else ""


def _extract_data_point_lines(brief_data: dict[str, Any]) -> list[str]:
    data_points = brief_data.get("data_points")
    if not isinstance(data_points, list):
        return []
    lines: list[str] = []
    for dp in data_points:
        if not isinstance(dp, dict):
            continue
        claim = str(dp.get("claim") or "").strip()
        if not claim:
            continue
        src = _dp_source_label(dp)
        usable = str(dp.get("usable_as") or "").strip()
        lines.append(f"DataPoint ({src}): {claim} {usable}".strip())
    return lines


def _extract_existing_content_lines(landscape: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    fields = ("title", "angle", "what_it_covers", "what_it_misses", "engagement_signal")
    for ec in landscape.get("existing_content", []):
        if isinstance(ec, dict):
            ec_parts = [str(ec.get(k) or "").strip() for k in fields]
            ec_text = " ".join(p for p in ec_parts if p)
            if ec_text:
                lines.append(f"ExistingContent: {ec_text}")
    return lines


def _extract_gap_lines(landscape: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for gap in landscape.get("underserved_gaps", []):
        gap_str = str(gap).strip()
        if gap_str:
            lines.append(f"Gap: {gap_str}")
    return lines


def _extract_landscape_lines(brief_data: dict[str, Any]) -> list[str]:
    landscape = brief_data.get("landscape")
    if not isinstance(landscape, dict):
        return []
    lines = _extract_existing_content_lines(landscape)
    lines.extend(_extract_gap_lines(landscape))
    return lines


def _extract_misconception_lines(brief_data: dict[str, Any]) -> list[str]:
    aud = brief_data.get("audience_insights")
    if not isinstance(aud, dict):
        return []
    lines: list[str] = []
    for m in aud.get("misconceptions", []):
        if isinstance(m, dict):
            myth = str(m.get("myth") or "").strip()
            reality = str(m.get("reality") or "").strip()
            if myth or reality:
                lines.append(f"Misconception: {myth} -> {reality}")
    return lines


def _format_single_angle(ang: dict[str, Any]) -> str:
    grounded_items = ang.get("grounded_in")
    grounded = ""
    if isinstance(grounded_items, list):
        grounded = " ".join(str(x) for x in grounded_items if x)
    name = str(ang.get("name") or "")
    hook = str(ang.get("hook") or "")
    why_now = str(ang.get("why_now") or "")
    return f"{name}: {hook} {why_now} {grounded}".strip()


def _extract_angle_lines(brief_data: dict[str, Any]) -> list[str]:
    angles = brief_data.get("angles_discovered")
    if not isinstance(angles, list):
        return []
    lines: list[str] = []
    for ang in angles:
        if isinstance(ang, dict):
            ang_text = _format_single_angle(ang)
            if ang_text:
                lines.append(f"Angle: {ang_text}")
    return lines


def _extract_brief_corpus_lines(brief_data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    topic_val = str(brief_data.get("topic") or brief_data.get("title") or "").strip()
    if topic_val:
        lines.append(f"Topic: {topic_val}")
    lines.extend(_extract_data_point_lines(brief_data))
    lines.extend(_extract_landscape_lines(brief_data))
    lines.extend(_extract_misconception_lines(brief_data))
    lines.extend(_extract_angle_lines(brief_data))
    return lines


def _extract_candidate_published_date(
    matched_prov: dict[str, Any] | None,
    src: dict[str, Any],
    brief_data: dict[str, Any],
) -> str | None:
    if matched_prov and matched_prov.get("published_at"):
        return str(matched_prov["published_at"])
    if src.get("published_at"):
        return str(src["published_at"])
    metadata = brief_data.get("metadata")
    if isinstance(metadata, dict) and metadata.get("published_at"):
        return str(metadata["published_at"])
    if brief_data.get("published_at_utc"):
        return str(brief_data["published_at_utc"])
    research_date = brief_data.get("research_date")
    if research_date and re.match(r"^\d{4}-\d{2}-\d{2}$", str(research_date)):
        return f"{research_date}T00:00:00+00:00"
    return None


def _resolve_effective_published_date(
    candidate: str | None,
    strict_capture_required: bool,
    default_iso: str,
) -> str | None:
    if candidate and _is_valid_iso(candidate):
        return candidate
    if strict_capture_required:
        return None
    return default_iso


def _resolve_retrieval_date(
    matched_prov: dict[str, Any] | None,
    default_iso: str,
) -> str:
    if matched_prov and matched_prov.get("retrieved_at"):
        return str(matched_prov["retrieved_at"])
    return default_iso


def _find_matching_provenance(
    url: str,
    provenance_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if url in provenance_map:
        return provenance_map[url]
    if provenance_map:
        return next(iter(provenance_map.values()))
    return None


def _resolve_authentic_pub_date(
    primary_source: dict[str, Any],
    provenance_map: dict[str, dict[str, Any]],
    now_iso: str,
) -> str:
    primary_prov = _find_matching_provenance(primary_source["url"], provenance_map)
    if primary_prov and primary_prov.get("published_at"):
        return str(primary_prov["published_at"])
    if primary_source.get("published_at"):
        return str(primary_source["published_at"])
    return now_iso


def _resolve_snapshot_file_and_sha(
    best_cap_file: str | None,
    best_cap_sha: str | None,
    primary_source: dict[str, Any],
    strict_capture_required: bool,
) -> tuple[str, str]:
    if strict_capture_required and best_cap_file and best_cap_sha:
        return best_cap_file, best_cap_sha
    sid = primary_source["id"]
    return f"source_evidence_{sid}.txt", primary_source["content_sha256"]


def _find_best_capture(
    sec_tokens: set[str],
    capture_files_map: dict[str, tuple[str, str]],
) -> tuple[str | None, str | None]:
    if not capture_files_map:
        return None, None
    best_file = None
    best_sha = None
    best_overlap = -1
    for cap_name, (cap_content, cap_sha) in capture_files_map.items():
        cap_toks = _extract_content_tokens(cap_content)
        overlap = len([t for t in sec_tokens if _tokens_match(t, cap_toks)])
        if overlap > best_overlap:
            best_overlap = overlap
            best_file = f"news_source_capture/{cap_name}"
            best_sha = cap_sha
    return best_file, best_sha


def _check_quantitative_figures(
    sec_text: str, target_corpus: str, should_verify: bool
) -> tuple[bool, list[str]]:
    if not should_verify:
        return False, []
    cleaned_text = re.sub(r"\b(?:section|scene|part|đoạn|phần)\s+\d+\b", "", sec_text, flags=re.IGNORECASE)
    figures = re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", cleaned_text)
    missing = [f for f in figures if f not in target_corpus and f.rstrip("%") not in target_corpus]
    return bool(missing), missing


def _check_semantic_grounding(
    sec_text: str, target_corpus: str, publisher: str, canonical_url: str,
    strict_capture_required: bool, is_en_us: bool,
) -> tuple[bool, str]:
    from lib.fixed_niche.claim_grounding import verify_independent_claim

    grounding = verify_independent_claim(
        statement=sec_text,
        snapshot_text=target_corpus,
        publisher=publisher,
        canonical_url=canonical_url,
    )
    if grounding.get("verification_status") != "INDEPENDENT_FACT_CHECK_VERIFIED":
        if strict_capture_required or is_en_us:
            return True, str(grounding.get("attestation") or "")
        return False, ""

    sec_tokens = _extract_content_tokens(sec_text)
    source_tokens = _extract_content_tokens(target_corpus)
    common_tokens = {tok for tok in sec_tokens if _tokens_match(tok, source_tokens)}

    if is_en_us:
        if len(common_tokens) < _min_token_overlap(len(sec_tokens)):
            return True, f"found {len(common_tokens)} matching terms"
    elif len(sec_tokens) >= 5 and not common_tokens:
        return True, f"found {len(common_tokens)} matching terms"
    return False, ""


def _format_claim_error(
    sec_id: str, idx: int, has_fig_err: bool, missing_figs: list[str],
    has_sem_err: bool, sem_reason: str, strict_capture_required: bool,
) -> str | None:
    corpus_desc = "captured source files" if strict_capture_required else "frozen research_brief.json"
    claim_id = f"C{idx + 1:03d}"
    if has_fig_err:
        return f"Section '{sec_id}' ({claim_id}) asserts unsubstantiated figure(s) {missing_figs} not present in {corpus_desc}"
    if has_sem_err:
        return f"Section '{sec_id}' ({claim_id}) lacks substantive semantic/entity grounding in {corpus_desc} ({sem_reason})"
    return None


def _load_provenance_map(capture_dir: Path) -> dict[str, dict[str, Any]]:
    provenance_map: dict[str, dict[str, Any]] = {}
    if not capture_dir.is_dir():
        return provenance_map
    for prov_file in sorted(capture_dir.glob("*provenance*.json")):
        try:
            p_data = json.loads(prov_file.read_text(encoding="utf-8"))
            if isinstance(p_data, dict):
                provenance_map[prov_file.name] = p_data
                if p_data.get("url"):
                    provenance_map[p_data["url"]] = p_data
        except Exception:
            pass
    return provenance_map


def _read_capture_file_content(cap_file: Path) -> str:
    try:
        if cap_file.suffix == ".json":
            cap_data = json.loads(cap_file.read_text(encoding="utf-8"))
            return str(cap_data.get("text") or "").strip()
        return cap_file.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _load_capture_files(
    capture_dir: Path,
) -> tuple[list[str], dict[str, tuple[str, str]], list[str]]:
    capture_corpus_lines: list[str] = []
    capture_files_map: dict[str, tuple[str, str]] = {}
    captured_source_lines: list[str] = []
    if not capture_dir.is_dir():
        return capture_corpus_lines, capture_files_map, captured_source_lines

    candidates = sorted(list(capture_dir.glob("*.txt")) + list(capture_dir.glob("*extracted*.json")))
    for cap_file in candidates:
        cap_content = _read_capture_file_content(cap_file)
        if cap_content:
            capture_corpus_lines.append(cap_content)
            cap_sha = hashlib.sha256(cap_content.encode("utf-8")).hexdigest()
            capture_files_map[cap_file.name] = (cap_content, cap_sha)
            captured_source_lines.append(f"CapturedSource ({cap_file.name}): {cap_content[:4000]}")
    return capture_corpus_lines, capture_files_map, captured_source_lines


def _extract_source_metadata(
    capture_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, tuple[str, str]], list[str]]:
    provenance_map = _load_provenance_map(capture_dir)
    cap_lines, cap_map, cap_src_lines = _load_capture_files(capture_dir)
    return provenance_map, cap_lines, cap_map, cap_src_lines


def _is_cta_section(section: dict[str, Any], idx: int, total_sections: int) -> bool:
    sec_id = str(section.get("id") or "").lower()
    sec_label = str(section.get("label") or "").lower()
    sec_type = str(section.get("type") or "").lower()
    if any(k in sec_id or k in sec_label or k in sec_type for k in ("cta", "outro", "call_to_action", "call to action")):
        return True
    sec_text = (
        section.get("text_vi") or section.get("text") or section.get("narration") or ""
    ).strip().lower()
    cta_patterns = (
        r"\b(?:follow|subscribe|star\s+(?:the\s+|our\s+)?repo|defensive blueprint|theo dõi|đăng ký)\b",
        r"\b(?:follow for daily|star the repo|leave a comment|what do you think)\b",
    )
    is_last = (idx >= total_sections - 1) and (total_sections > 1)
    has_cta_text = any(bool(re.search(p, sec_text, re.IGNORECASE)) for p in cta_patterns)
    if is_last and has_cta_text:
        return True
    if re.search(r"^\s*(?:follow|subscribe|star\s+(?:the\s+)?repo|theo dõi|đăng ký)\b", sec_text, re.IGNORECASE):
        return True
    return False


def _build_claim_entry(
    sec_id: str,
    sec_text: str,
    primary_source_id: str,
    is_verified: bool,
    now_iso: str,
    is_cta: bool = False,
) -> dict[str, Any]:
    claim_text = sec_text[:180].strip() or "Nội dung tin tức công nghệ đã được xác thực."
    return {
        "section_id": sec_id,
        "claim": claim_text,
        "classification": "opinion" if is_cta else "reported_fact",
        "consequential": False,
        "source_ids": [primary_source_id],
        "reviewer": "Ban biên tập OpenMontage (Tự động hóa)",
        "reviewed_at": now_iso,
        "review_status": "approved" if is_verified else "rejected",
    }


def _create_ledger_claim(
    idx: int, sec_text: str, is_verified: bool, primary_source: dict[str, Any],
    primary_title: str, target_corpus: str, capture_files_map: dict[str, tuple[str, str]],
    provenance_map: dict[str, dict[str, Any]], strict_capture_required: bool, now_iso: str,
) -> dict[str, Any]:
    sec_tokens = _extract_content_tokens(sec_text)
    best_cap_file, best_cap_sha = _find_best_capture(sec_tokens, capture_files_map)
    snap_file, snap_sha = _resolve_snapshot_file_and_sha(
        best_cap_file, best_cap_sha, primary_source, strict_capture_required
    )
    authentic_pub_date = _resolve_authentic_pub_date(primary_source, provenance_map, now_iso)
    return {
        "claim_id": f"C{idx + 1:03d}",
        "statement": sec_text,
        "confidence": "verified" if is_verified else "unverified",
        "scope": {"market": "US", "as_of": now_iso[:10]},
        "source": {
            "canonical_url": primary_source["url"],
            "publisher": str(primary_title),
            "published_at": authentic_pub_date,
            "retrieved_at": now_iso,
            "snapshot_file": snap_file,
            "snapshot_sha256": snap_sha,
        },
        "evidence_excerpt": target_corpus[:4000],
        "script_spans": [sec_text],
        "verdict": "APPROVED" if is_verified else "REJECTED",
    }
