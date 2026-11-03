"""Clean Architecture Domain Helpers and Outbound Ports for Candidate Discovery.

Provides:
- CandidateConsumerPort (typing.Protocol): Outbound port for candidate removal/consumption.
- Candidate consumption registration mechanism for decoupled adapter wiring.
- Pure parsing and normalization routines for candidate records.

Adheres to Clean Architecture Inward Dependency & Module Sizing Rules (<450 lines).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set, Tuple, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CandidateConsumerPort(Protocol):
    """Outbound port for candidate consumption / removal logic."""

    def consume_candidates(self, candidate_ids: Sequence[str]) -> Any:
        """Mark candidate IDs as consumed in external services."""
        ...


_registered_consumers: List[CandidateConsumerPort] = []


def register_candidate_consumer(consumer: CandidateConsumerPort) -> None:
    """Register an outbound consumer adapter adhering to CandidateConsumerPort."""
    if consumer not in _registered_consumers:
        _registered_consumers.append(consumer)


def get_registered_candidate_consumers() -> List[CandidateConsumerPort]:
    """Retrieve currently registered candidate consumer adapters."""
    return list(_registered_consumers)


def parse_timestamp(val: Any) -> float:
    """Parse ISO timestamp or date into float epoch seconds."""
    if not val:
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass

        if "-" in s:
            date_part = s.split()[0]
            parts = [int(p) for p in date_part.split("-")]
            dt = datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
        elif "/" in s:
            date_part = s.split()[0]
            parts = [int(p) for p in date_part.split("/")]
            if parts[0] > 1000:
                dt = datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
            else:
                dt = datetime(parts[2], parts[1], parts[0], tzinfo=timezone.utc)
        else:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def sort_candidates_by_recency(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort candidates so recent/latest published items appear first."""
    def recency_key(pair: Tuple[int, Dict[str, Any]]) -> Tuple[int, int, float, int]:
        idx, item = pair
        is_news = 1 if (item.get("content_kind") == "news" and not item.get("is_evergreen")) else 0
        has_date = 1 if item.get("has_explicit_date") else 0
        ts = parse_timestamp(item.get("published_at_utc")) if has_date else 0.0
        return (is_news, has_date, ts, -idx)

    sorted_indexed = sorted(enumerate(candidates), key=recency_key, reverse=True)
    return [item for _, item in sorted_indexed]


def normalize_candidate_dict(
    cand: Dict[str, Any],
    cid: str,
    verdict: Any,
) -> Dict[str, Any]:
    """Normalize an eligible candidate into a uniform dictionary representation."""
    content_kind = getattr(verdict, "content_kind", None) or cand.get("content_kind", "evergreen_explainer")
    topic_family = getattr(verdict, "topic_family", None)
    normalized = dict(cand)
    normalized["candidate_id"] = cid
    normalized["id"] = cid
    normalized["topic_family"] = topic_family
    normalized["content_kind"] = content_kind
    has_pub = bool(cand.get("published_at") or cand.get("published_at_utc"))
    normalized["has_explicit_date"] = has_pub
    pub_at = cand.get("published_at") or cand.get("published_at_utc") or datetime.now(timezone.utc).isoformat()
    normalized["published_at_utc"] = pub_at
    normalized["published_at"] = pub_at
    pub_name = str(cand.get("publisher") or "Unknown")
    normalized["publisher"] = pub_name
    normalized["normalized_publisher"] = str(cand.get("normalized_publisher") or pub_name).lower()
    url = cand.get("canonical_url") or cand.get("url") or ""
    normalized["url"] = url
    normalized["canonical_url"] = url
    body = cand.get("body") or cand.get("summary") or cand.get("description") or ""
    normalized["body"] = body
    normalized["summary"] = cand.get("summary") or body[:300]
    content_h = (
        cand.get("content_hash")
        or hashlib.sha256(
            f"{str(cand.get('title', '')).strip().lower()}|{url.strip().lower()}|{body[:500].strip().lower()}".encode("utf-8")
        ).hexdigest()
    )
    normalized["content_hash"] = content_h
    normalized["raw_provenance"] = cand.get("raw_provenance") or {
        "source_id": cid,
        "source_feed": "fixed_niche",
    }
    return normalized


def load_candidates_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """Safely load candidates from a JSON or YAML file."""
    if not file_path.is_file():
        return []
    try:
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix in (".yaml", ".yml"):
            import yaml
            raw = yaml.safe_load(content)
        else:
            raw = json.loads(content)

        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("candidates", []) or raw.get("positive_cases", []) or raw.get("items", [])
        return []
    except Exception as e:
        logger.warning("Failed loading candidates from %s: %s", file_path, e)
        return []
