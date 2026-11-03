"""Convert Muse's live editorial discovery into the existing raw-news contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema.exceptions import ValidationError

from tools.news.newsnow_adapter import NewsNowAdapter

logger = logging.getLogger(__name__)


class MuseNewsError(RuntimeError):
    pass


def _parse_response(content: object) -> list[dict]:
    if isinstance(content, str):
        stripped = content.strip()
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].lower() in ("```", "```json") and lines[-1] == "```":
            content = "\n".join(lines[1:-1])
    try:
        raw = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise MuseNewsError("Muse discovery did not return a JSON array") from exc
    if not isinstance(raw, list) or len(raw) > 100:
        raise MuseNewsError("Muse discovery did not return a bounded JSON array")
    return raw


def _normalize_item(item: object, adapter: NewsNowAdapter) -> tuple[dict, datetime, str] | None:
    if not isinstance(item, dict):
        return None
    try:
        url = urlsplit(item.get("url", ""))
        raw_date = item.get("published_at")
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return None
        if not isinstance(raw_date, str) or datetime.fromisoformat(raw_date.replace("Z", "+00:00")).tzinfo is None:
            return None
        candidate = adapter.normalize_item(item)
        published = datetime.fromisoformat(candidate["published_at_utc"])
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
        return None
    return dict(item), published, candidate["canonical_url"]


def _accept_item(item: dict, published: datetime, canonical_url: str, cutoff: datetime, now: datetime, seen: set[str]) -> dict | None:
    if not cutoff <= published <= now or canonical_url in seen:
        return None
    normalized = dict(item)
    normalized["source_feed"] = "muse"
    seen.add(canonical_url)
    return normalized


def discover_news(client, max_age_hours: float, *, now: datetime | None = None, limit: int = 30) -> list[dict]:
    if not math.isfinite(max_age_hours) or not 0 < max_age_hours <= 720 or not 1 <= limit <= 100:
        raise ValueError("Invalid discovery freshness window or limit")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Discovery time must have a timezone")
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    prompt_path = Path(__file__).resolve().parents[2] / "scripts/prompts/muse_news_discovery.prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8").format(now=now.isoformat(), cutoff=cutoff.isoformat(), limit=limit)
    raw = _parse_response(client.chat("us-ai-agent-engineering:news-discovery", prompt))
    if not raw:
        logger.info("Muse returned no discovery leads")
        return []
    adapter = NewsNowAdapter()
    accepted = []
    seen = set()
    valid_count = 0
    for item in raw:
        normalized_item = _normalize_item(item, adapter)
        if normalized_item is None:
            continue
        valid_count += 1
        raw_item, published, canonical_url = normalized_item
        normalized = _accept_item(raw_item, published, canonical_url, cutoff, now, seen)
        if normalized is None:
            continue
        accepted.append(normalized)
        if len(accepted) >= limit:
            break
    if not valid_count:
        raise MuseNewsError("Muse returned no structurally valid dated source leads")
    logger.info("Muse returned %d leads; %d passed structure and %d passed freshness and deduplication", len(raw), valid_count, len(accepted))
    return accepted
