"""Gateway Daily News feed compatibility helpers.

Migrated from legacy direct NewsNow scraping to Toolcase Gateway /custom/daily-news.
Delegates to discovery-first DailyNewsGatewayClient with SSRF-safe TOOLCASE_GATEWAY_URL resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tools.news.daily_news_gateway import (
    DEFAULT_SOURCES,
    DEFAULT_TOOLCASE_GATEWAY_URL,
    DailyNewsGatewayClient,
    resolve_gateway_base_url,
)

__all__ = [
    "DEFAULT_SOURCES",
    "DEFAULT_TOOLCASE_GATEWAY_URL",
    "fetch_feed",
    "refresh_feed",
    "write_feed",
    "consume_candidates",
    "resolve_gateway_base_url",
]


def fetch_feed(
    base_url: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Fetch the gateway's latest ranked news items.

    Resolves base URL via TOOLCASE_GATEWAY_URL if base_url is omitted.
    """
    client = DailyNewsGatewayClient(base_url=base_url)
    return client.fetch_feed(base_url=base_url, sources=sources, limit=limit)


def write_feed(
    base_url: Optional[str] = None,
    output: Path | str = Path("data/gateway_daily_news_feed.json"),
    minimum: int = 3,
    sources: Optional[Sequence[str]] = None,
    limit: int = 30,
) -> int:
    """Fetch latest gateway items and write them to the output path atomically."""
    items = fetch_feed(base_url, sources=sources, limit=limit)
    client = DailyNewsGatewayClient(base_url=base_url)
    return client.write_feed(
        base_url=base_url,
        output=output,
        minimum=minimum,
        sources=sources,
        limit=limit,
        items=items,
    )


def refresh_feed(
    base_url: Optional[str],
    output: Path | str,
    minimum: int,
    max_age_hours: float,
    topics: Optional[List[str]] = None,
    sources: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Atomically cache only fresh, ranked Gateway discovery candidates."""
    return DailyNewsGatewayClient(base_url=base_url).refresh_feed(
        base_url=base_url,
        output=output,
        minimum=minimum,
        max_age_hours=max_age_hours,
        topics=topics,
        sources=sources,
    )


def consume_candidates(
    candidate_ids: Sequence[str],
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark candidate IDs as consumed on the Daily News Gateway (removal logic)."""
    client = DailyNewsGatewayClient(base_url=base_url)
    return client.consume_candidates(candidate_ids=candidate_ids, base_url=base_url)
