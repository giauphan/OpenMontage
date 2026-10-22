"""Fail-closed validation for frozen source evidence bound to a news script."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_SOURCE_AGE_HOURS = 24 * 30
EVIDENCE_RELATIVE_PATH = Path("artifacts/news_evidence.json")
SCRIPT_VI_REL = "artifacts/script_vi.json"
SCRIPT_EN_REL = "artifacts/script_en_US.json"
SCRIPT_CANONICAL_REL = "artifacts/script.json"


def _aware_datetime(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: required aware ISO-8601 timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        errors.append(f"{label}: invalid ISO-8601 timestamp")
        return None
    try:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            errors.append(f"{label}: timestamp must include timezone")
            return None
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        errors.append(f"{label}: timestamp is outside the supported datetime range")
        return None


def _normalized_source_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        if scheme not in {"http", "https"} or not hostname:
            return None
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        host = hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if port is not None and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
            host = f"{host}:{port}"
        return urlunsplit((scheme, host, parsed.path or "/", parsed.query, ""))
    except ValueError:
        return None


def _safe_relative_file(root: Path, value: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: required project-relative path")
        return None
    posix = PurePosixPath(value)
    candidate = root / value
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError, RuntimeError):
        errors.append(f"{label}: missing file or path escapes project directory")
        return None
    if posix.is_absolute() or ".." in posix.parts or not resolved.is_file():
        errors.append(f"{label}: must identify a project-contained regular file")
        return None
    return resolved


def _validate_source_age_and_now(
    max_source_age_hours: float,
    now: datetime | None,
    errors: list[str],
) -> datetime:
    if isinstance(max_source_age_hours, bool) or not isinstance(max_source_age_hours, (int, float)):
        errors.append("max_source_age_hours must be a finite number in (0, 720]")
    elif max_source_age_hours <= 0 or max_source_age_hours > MAX_SOURCE_AGE_HOURS:
        errors.append("max_source_age_hours must be a finite number in (0, 720]")
    elif isinstance(max_source_age_hours, float) and not math.isfinite(max_source_age_hours):
        errors.append("max_source_age_hours must be a finite number in (0, 720]")
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        errors.append("now must be a timezone-aware datetime")
        return datetime.now(timezone.utc)
    return now.astimezone(timezone.utc)


def _find_script_rel(root: Path) -> str:
    if (root / SCRIPT_EN_REL).is_file():
        return SCRIPT_EN_REL
    if (root / SCRIPT_VI_REL).is_file():
        return SCRIPT_VI_REL
    if (root / SCRIPT_CANONICAL_REL).is_file():
        return SCRIPT_CANONICAL_REL
    return SCRIPT_VI_REL


def _validate_source_content(
    content_path: Path | None,
    source: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    if not content_path:
        return
    try:
        content = content_path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        if source.get("content_sha256") != actual_hash:
            errors.append(f"{label}.content_sha256: frozen content hash mismatch")
        if not content.strip():
            errors.append(f"{label}: frozen source content is empty")
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            errors.append(f"{label}: frozen source content must be valid UTF-8")
        excerpt = source.get("excerpt")
        try:
            excerpt_bytes = excerpt.encode("utf-8") if isinstance(excerpt, str) else b""
        except UnicodeEncodeError:
            excerpt_bytes = b""
        if not isinstance(excerpt, str) or not excerpt.strip() or not excerpt_bytes or excerpt_bytes not in content:
            errors.append(f"{label}.excerpt: required valid UTF-8 text contained in frozen content")
    except OSError as exc:
        errors.append(f"{label}: cannot read frozen content: {exc}")


def _validate_source_dates(
    dates: dict[str, datetime | None],
    label: str,
    now_utc: datetime,
    max_source_age_hours: float,
    errors: list[str],
) -> None:
    published, updated, retrieved = dates.get("published_at"), dates.get("updated_at"), dates.get("retrieved_at")
    if updated and published and updated < published:
        errors.append(f"{label}: updated_at cannot precede published_at")
    if retrieved and published and retrieved < published:
        errors.append(f"{label}: retrieved_at cannot precede published_at")
    if retrieved and updated and retrieved < updated:
        errors.append(f"{label}: retrieved_at cannot precede updated_at")
    freshness_date = updated or published
    if (
        freshness_date
        and isinstance(max_source_age_hours, (int, float))
        and not isinstance(max_source_age_hours, bool)
        and 0 < max_source_age_hours <= MAX_SOURCE_AGE_HOURS
        and (not isinstance(max_source_age_hours, float) or math.isfinite(max_source_age_hours))
    ):
        age = (now_utc - freshness_date).total_seconds() / 3600
        if age > max_source_age_hours:
            errors.append(f"{label}: source is stale ({age:.2f}h; limit {max_source_age_hours:g}h)")


def _validate_single_source(
    source: Any,
    i: int,
    root: Path,
    now_utc: datetime,
    max_source_age_hours: float,
    source_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    label = f"sources[{i}]"
    if not isinstance(source, dict):
        errors.append(f"{label}: must be an object")
        return
    sid, url = source.get("id"), source.get("url")
    if not isinstance(sid, str) or not sid.strip() or sid in source_by_id:
        errors.append(f"{label}.id: required unique non-empty string")
    else:
        source_by_id[sid] = source
    parsed_url = None
    if isinstance(url, str):
        try:
            parsed_url = urlsplit(url)
            if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.hostname:
                parsed_url = None
            elif parsed_url.port is not None and not 1 <= parsed_url.port <= 65535:
                parsed_url = None
        except ValueError:
            parsed_url = None
    if parsed_url is None:
        errors.append(f"{label}.url: must be a valid absolute HTTP(S) URL")
    if source.get("status") != "available":
        errors.append(f"{label}: source status must be available; outages/unverified sources fail closed")
    dates: dict[str, datetime | None] = {}
    for field in ("published_at", "updated_at", "retrieved_at"):
        dates[field] = _aware_datetime(source.get(field), f"{label}.{field}", errors)
        if dates[field] and dates[field] > now_utc:
            errors.append(f"{label}.{field}: timestamp is in the future")
    content_path = _safe_relative_file(root, source.get("content_path"), f"{label}.content_path", errors)
    _validate_source_content(content_path, source, label, errors)
    _validate_source_dates(dates, label, now_utc, max_source_age_hours, errors)


def _validate_script_sections(script_sections: list[Any], errors: list[str]) -> list[str]:
    script_ids: list[str] = []
    for i, section in enumerate(script_sections):
        if not isinstance(section, dict):
            errors.append(f"script sections[{i}] must be an object")
            continue
        section_id = section.get("id")
        if not isinstance(section_id, (str, int)) or isinstance(section_id, bool) or not str(section_id).strip():
            errors.append(f"script sections[{i}].id must be a non-empty string or integer")
            continue
        section_text = section.get("text_vi")
        if not isinstance(section_text, str) or not section_text.strip():
            section_text = section.get("text")
        if not isinstance(section_text, str) or not section_text.strip():
            errors.append(f"script sections[{i}] must contain non-empty string text_vi or text")
        normalized_id = str(section_id)
        if normalized_id in script_ids:
            errors.append(f"script sections[{i}].id must be unique")
        script_ids.append(normalized_id)
    return script_ids


def _validate_claim_sources(
    refs: Any,
    label: str,
    source_by_id: dict[str, dict[str, Any]],
    reviewed_at: datetime | None,
    consequential: bool,
    errors: list[str],
) -> None:
    if not isinstance(refs, list) or not refs:
        errors.append(f"{label}.source_ids must be a non-empty array")
        return
    referenced_sources = []
    if any(refs[index] in refs[:index] for index in range(len(refs))):
        errors.append(f"{label}.source_ids must not contain duplicate source references")
    for sid in refs:
        if not isinstance(sid, str) or sid not in source_by_id:
            errors.append(f"{label}: source_ids contain missing/invalid source reference {sid!r}")
        else:
            referenced_sources.append(source_by_id[sid])
    publishers = {s.get("publisher_id") for s in referenced_sources if isinstance(s.get("publisher_id"), str) and s.get("publisher_id").strip()}
    distinct_source_ids = {sid for sid in refs if isinstance(sid, str) and sid in source_by_id}
    normalized_urls = {_normalized_source_url(s.get("url")) for s in referenced_sources}
    content_hashes = {s.get("content_sha256") for s in referenced_sources if isinstance(s.get("content_sha256"), str)}
    if consequential:
        if len(distinct_source_ids) < 2 or len(publishers) < 2:
            errors.append(f"{label}: consequential claims require corroboration from at least two distinct attributable publishers")
        if None in normalized_urls or len(normalized_urls) < 2:
            errors.append(f"{label}: consequential corroboration requires distinct normalized source URLs")
        if len(content_hashes) < 2:
            errors.append(f"{label}: consequential corroboration requires distinct frozen source content")
    if reviewed_at and referenced_sources:
        snapshots = [_aware_datetime(s.get("retrieved_at"), f"{label} referenced source retrieved_at", errors) for s in referenced_sources]
        valid_snapshots = [sn for sn in snapshots if sn is not None]
        if valid_snapshots and reviewed_at < max(valid_snapshots):
            errors.append(f"{label}.reviewed_at must be at or after the latest referenced source snapshot")


def _validate_single_claim(
    claim: Any,
    i: int,
    script_ids: list[str],
    source_by_id: dict[str, dict[str, Any]],
    now_utc: datetime,
    claim_sections: set[str],
    errors: list[str],
) -> None:
    label = f"claims[{i}]"
    if not isinstance(claim, dict):
        errors.append(f"{label} must be an object")
        return
    section_id = claim.get("section_id")
    if not isinstance(section_id, (str, int)) or isinstance(section_id, bool) or not str(section_id).strip():
        errors.append(f"{label}.section_id must be a non-empty string or integer")
        return
    section_id_str = str(section_id)
    claim_sections.add(section_id_str)
    if section_id_str not in script_ids:
        errors.append(f"{label}: section_id does not exist in script")
    if not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
        errors.append(f"{label}.claim must be non-empty text")
    classification = claim.get("classification")
    if not isinstance(classification, str) or classification not in {"reported_fact", "attribution", "inference", "opinion"}:
        errors.append(f"{label}.classification must be reported_fact, attribution, inference, or opinion")
    consequential = claim.get("consequential")
    if not isinstance(consequential, bool):
        errors.append(f"{label}.consequential must be a boolean")
    elif consequential and claim.get("authority_attested") is not True:
        errors.append(f"{label}.authority_attested must be true for consequential claims")
    if claim.get("review_status") != "approved":
        errors.append(f"{label}.review_status must be 'approved'; pending, rejected, or missing review fails closed")
    reviewer = claim.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append(f"{label}.reviewer must identify the human reviewer")
    reviewed_at = _aware_datetime(claim.get("reviewed_at"), f"{label}.reviewed_at", errors)
    if reviewed_at and reviewed_at > now_utc:
        errors.append(f"{label}.reviewed_at: timestamp is in the future")
    _validate_claim_sources(claim.get("source_ids"), label, source_by_id, reviewed_at, consequential is True, errors)


def _validate_contradictions(
    conflicts: list[Any],
    source_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    for i, conflict in enumerate(conflicts):
        label = f"contradictions[{i}]"
        if not isinstance(conflict, dict) or conflict.get("status") != "resolved":
            errors.append(f"{label} must be an object with status='resolved'; unresolved/corrected claims block publication")
            continue
        if not isinstance(conflict.get("resolution"), str) or not conflict["resolution"].strip():
            errors.append(f"{label}.resolution must document the resolution")
        refs = conflict.get("source_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(sid, str) or sid not in source_by_id for sid in refs):
            errors.append(f"{label}.source_ids must reference existing sources supporting the resolution")


def validate_news_evidence(
    project_dir: str | Path,
    max_source_age_hours: float,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return machine-readable gate results. No network access or evidence creation occurs."""
    errors: list[str] = []
    now_utc = _validate_source_age_and_now(max_source_age_hours, now, errors)

    try:
        root = Path(project_dir)
    except (TypeError, ValueError, OSError):
        return {"ok": False, "status": "failed", "errors": errors + ["project_dir must be a valid directory path"]}
    if not root.is_dir():
        errors.append("project_dir must be an existing directory")
        return {"ok": False, "status": "failed", "errors": errors}

    script_rel = _find_script_rel(root)
    script = _safe_relative_file(root, script_rel, "script", errors)
    evidence_path = _safe_relative_file(root, EVIDENCE_RELATIVE_PATH.as_posix(), "evidence artifact", errors)
    if script is None or evidence_path is None:
        return {"ok": False, "status": "failed", "errors": errors}
    try:
        script_bytes = script.read_bytes()
        script_json = json.loads(script_bytes)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "failed", "errors": [f"cannot read/parse canonical JSON artifacts: {exc}"]}

    script_name = Path(script_rel).name
    script_sections = script_json.get("sections") if isinstance(script_json, dict) else None
    if not isinstance(script_json, dict) or not isinstance(script_sections, list) or not script_sections:
        errors.append(f"{script_name} must be an object" if not isinstance(script_json, dict) else f"{script_name} must contain a non-empty sections array")
        script_sections = []

    if not isinstance(evidence, dict) or evidence.get("version") != "2.0":
        return {"ok": False, "status": "failed", "errors": errors + ["news_evidence.json must be a version 2.0 object"]}
    if evidence.get("script_sha256") != hashlib.sha256(script_bytes).hexdigest():
        errors.append(f"script binding mismatch: script_sha256 must hash the complete current {script_name} bytes")

    claims = evidence.get("claims") if isinstance(evidence.get("claims"), list) else None
    sources = evidence.get("sources") if isinstance(evidence.get("sources"), list) else None
    conflicts = evidence.get("contradictions") if isinstance(evidence.get("contradictions"), list) else None
    if not claims:
        errors.append("claims must be a non-empty array")
    if not sources:
        errors.append("sources must be a non-empty array")
    if conflicts is None:
        errors.append("contradictions must be an array (use [] when none found)")

    source_by_id: dict[str, dict[str, Any]] = {}
    for i, source in enumerate(sources or []):
        _validate_single_source(source, i, root, now_utc, max_source_age_hours, source_by_id, errors)

    script_ids = _validate_script_sections(script_sections, errors)
    claim_sections: set[str] = set()
    for i, claim in enumerate(claims or []):
        _validate_single_claim(claim, i, script_ids, source_by_id, now_utc, claim_sections, errors)

    for section_id in script_ids:
        if section_id not in claim_sections:
            errors.append(f"script section {section_id!r} has no claim/provenance record")

    _validate_contradictions(conflicts or [], source_by_id, errors)

    return {
        "ok": not errors,
        "status": "passed" if not errors else "failed",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "errors": errors,
    }
