"""Shared fail-closed release boundary for projects identified as news."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lib.news_evidence import validate_news_evidence

NEWS_MAX_SOURCE_AGE_HOURS_ENV = "NEWS_MAX_SOURCE_AGE_HOURS"
NEWS_MARKERS = {"news", "newsnow", "daily_news", "daily-news", "news_video", "news-video"}
IDENTITY_FIELDS = {
    "pipeline", "pipeline_type", "project_type", "content_type", "source", "source_name",
    "source_feed", "provider", "feed", "newsnow", "news_source", "candidate_id",
    "project_id", "metadata", "identity", "project_metadata",
}


def _news_value(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower().replace(" ", "_")
        return (
            normalized in NEWS_MARKERS
            or normalized.startswith("newsnow_")
            or normalized.startswith("newsnow:")
            or normalized.startswith("cand_")
        )
    if isinstance(value, dict):
        return any(
            isinstance(key, str) and key.lower() in IDENTITY_FIELDS and _news_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_news_value(item) for item in value)
    return False


def _malformed_file_has_news_marker(path: Path) -> bool:
    try:
        raw = path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeError):
        return False
    compact = "".join(raw.split())
    return any(marker in compact for marker in (
        "newsnow", "daily_news", "daily-news", "news_video", "news-video",
        '"pipeline_type":"news"', '"source_feed":"news', '"candidate_id":"cand_',
    ))


def is_news_project(project_dir: str | Path, metadata: dict | None = None) -> bool:
    """Identify candidate and metadata-marked news projects, including renamed ones."""
    root = Path(project_dir)
    if root.name.lower().startswith("cand_"):
        return True

    # An evidence artifact is itself an explicit news marker. Its contents are
    # still validated later; malformed content must not downgrade identity.
    evidence_path = root / "artifacts/news_evidence.json"
    if evidence_path.exists() or evidence_path.is_symlink():
        return True

    documents: list[Any] = [metadata]
    for name in ("project.json", "publish_metadata.json", "artifacts/research_brief.json"):
        path = root / name
        if path.is_file():
            try:
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError):
                if _malformed_file_has_news_marker(path):
                    return True
                continue
    for document in documents:
        if not isinstance(document, dict):
            continue
        if _news_value(document):
            return True
        for key, value in document.items():
            if not isinstance(key, str):
                continue
            key_l = key.lower()
            if "newsnow" in key_l and value not in (None, False, "", [], {}):
                return True
            if key_l in {"news", "is_news", "news_project"} and value is True:
                return True
    return False


def require_news_evidence(project_dir: str | Path, env_max_age_hours: str | None = None,
                          metadata: dict | None = None) -> dict[str, Any] | None:
    """Validate evidence for news, returning None for unrelated video projects.

    The age limit is always supplied via NEWS_MAX_SOURCE_AGE_HOURS (or the
    explicit env_max_age_hours argument used by policy-focused callers).
    """
    if not is_news_project(project_dir, metadata):
        return None
    configured = env_max_age_hours if env_max_age_hours is not None else os.environ.get(NEWS_MAX_SOURCE_AGE_HOURS_ENV)
    if configured is None or not str(configured).strip():
        raise ValueError(f"{NEWS_MAX_SOURCE_AGE_HOURS_ENV} is required for news release")
    try:
        max_age = float(configured)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{NEWS_MAX_SOURCE_AGE_HOURS_ENV} must be a finite number in (0, 720]") from exc
    result = validate_news_evidence(project_dir, max_age)
    if not result.get("ok"):
        details = "; ".join(result.get("errors", [])) or "evidence validation failed"
        raise ValueError(f"News evidence gate failed for {Path(project_dir).name}: {details}")
    return result
