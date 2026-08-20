"""Fetch NewsNow source feeds and convert them to raw news items."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_SOURCES = ("hackernews", "github", "producthunt")


def _published_at(payload: dict[str, Any]) -> str:
    updated = payload.get("updatedTime")
    if isinstance(updated, (int, float)):
        return datetime.fromtimestamp(updated / 1000, timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _host(url: str) -> str:
    return urlparse(url).hostname or "newsnow"


def fetch_feed(base_url: str, sources: tuple[str, ...] = DEFAULT_SOURCES) -> list[dict[str, Any]]:
    """Fetch configured NewsNow source payloads and return schema-compatible items."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        endpoint = f"{base_url.rstrip('/')}/api/s?id={source}"
        request = Request(endpoint, headers={"Accept": "application/json"})
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            continue
        published_at = _published_at(payload)
        for raw in payload["items"]:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not url or not title:
                continue
            key = url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
            info = str(extra.get("info") or "").strip()
            item_id = str(raw.get("id") or key)
            items.append(
                {
                    "id": f"newsnow_{source}_{item_id}",
                    "url": url,
                    "title": title,
                    "publisher": _host(url),
                    "published_at": published_at,
                    "description": info,
                    "body": info,
                    "tags": [source],
                    "language": "en",
                    "source_feed": f"newsnow:{source}",
                    "extra": extra,
                }
            )
    return items


def write_feed(base_url: str, output: Path, minimum: int = 3) -> int:
    items = fetch_feed(base_url)
    if len(items) < minimum:
        raise RuntimeError(f"NewsNow returned {len(items)} valid items; need at least {minimum}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return len(items)
