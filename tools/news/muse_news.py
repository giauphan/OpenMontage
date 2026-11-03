"""Convert Muse's live editorial discovery into the existing raw-news contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from jsonschema.exceptions import ValidationError

from tools.news.newsnow_adapter import NewsNowAdapter

logger = logging.getLogger(__name__)


class MuseNewsError(RuntimeError):
    pass


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
    content = client.chat("us-ai-agent-engineering:news-discovery", prompt)
    if isinstance(content, str):
        fenced = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n```\s*", content, re.DOTALL | re.IGNORECASE)
        if fenced:
            content = fenced.group(1)
    try:
        raw = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise MuseNewsError("Muse discovery did not return a JSON array") from exc
    if not isinstance(raw, list) or len(raw) > 100:
        raise MuseNewsError("Muse discovery did not return a bounded JSON array")
    if not raw:
        logger.info("Muse returned no discovery leads")
        return []
    adapter = NewsNowAdapter()
    accepted = []
    seen = set()
    valid_count = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            url = urlsplit(item.get("url", ""))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                continue
            raw_date = item.get("published_at")
            if not isinstance(raw_date, str) or datetime.fromisoformat(raw_date.replace("Z", "+00:00")).tzinfo is None:
                continue
            candidate = adapter.normalize_item(item)
            published = datetime.fromisoformat(candidate["published_at_utc"])
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
            continue
        valid_count += 1
        canonical_url = candidate["canonical_url"]
        if not cutoff <= published <= now or canonical_url in seen:
            continue
        normalized = dict(item)
        normalized["source_feed"] = "muse"
        accepted.append(normalized)
        seen.add(canonical_url)
        if len(accepted) >= limit:
            break
    if not valid_count:
        raise MuseNewsError("Muse returned no structurally valid dated source leads")
    logger.info("Muse returned %d leads; %d passed structure and %d passed freshness and deduplication", len(raw), valid_count, len(accepted))
    return accepted
