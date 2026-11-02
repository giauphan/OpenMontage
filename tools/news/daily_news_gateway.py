"""Toolcase Gateway Daily News & Content Discovery Service Client.

Integrates OpenMontage with the native daily-news module hosted on Toolcase Gateway
(namespace prefix: /custom/daily-news).

Provides:
- SSRF-safe base URL resolution via TOOLCASE_GATEWAY_URL.
- Fetching normalized latest news feed items via GET /custom/daily-news/api/v1/feed.
- Tiered content discovery via POST /custom/daily-news/api/v1/discover.
- Candidate consumption / removal logic via POST /custom/daily-news/api/v1/consume.
- Health inspection via GET /custom/daily-news/health.

Clean Architecture & DDD compliant. Module size strictly under 450 lines.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_TOOLCASE_GATEWAY_PORT = 20129
DEFAULT_TOOLCASE_GATEWAY_URL = f"http://127.0.0.1:{DEFAULT_TOOLCASE_GATEWAY_PORT}"
DEFAULT_GATEWAY_NAMESPACE = "/custom/daily-news"
DEFAULT_SOURCES = ("hackernews", "github", "producthunt")
REQUEST_TIMEOUT_SECS = 20
APPLICATION_JSON = "application/json"
ACCEPT_JSON_HEADER = {"Accept": APPLICATION_JSON}
JSON_HEADERS = {"Content-Type": APPLICATION_JSON, "Accept": APPLICATION_JSON}


def _sanitize_log_val(val: Any, max_len: int = 120) -> str:
    """Sanitize strings before logging to prevent log injection (CWE-117)."""
    clean = re.sub(r"[\r\n\x00-\x1f\x7f-\x9f]", " ", str(val)).strip()
    return clean[:max_len]


def _resolve_safe_output_path(output: Path | str) -> Path:
    """Resolve and sanitize output path against traversal attacks (CWE-22 / CWE-73)."""
    raw_path = Path(output).expanduser()
    resolved = (Path.cwd() / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()

    repo_root = Path(__file__).resolve().parents[2]
    allowed_roots = (
        repo_root,
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not any(resolved == r or resolved.is_relative_to(r) for r in allowed_roots if r != Path(r.anchor)):
        raise ValueError(f"Path traversal detected or path outside allowed root: {output}")

    return resolved


def _extract_item_keys(raw: Dict[str, Any]) -> tuple[str, str]:
    """Extract and sanitize URL and title from raw feed item."""
    url = str(raw.get("url") or raw.get("canonical_url") or "").strip()
    title = str(raw.get("title") or "").strip()
    return url, title


def _normalize_feed_item(raw: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Normalize required fields, publisher, extra metadata, and tags."""
    item = dict(raw)
    if "url" not in item:
        item["url"] = url
    if "publisher" not in item:
        item["publisher"] = urlparse(url).hostname or "news"
    if "extra" not in item or not isinstance(item["extra"], dict):
        item["extra"] = {}
    if "retrieved_at" not in item["extra"]:
        item["extra"]["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    if "source_feed" not in item:
        source_tag = item["tags"][0] if item.get("tags") else "daily-news"
        item["source_feed"] = f"daily-news:{source_tag}"
    return item


def resolve_gateway_base_url(base_url: Optional[str] = None) -> str:
    """Resolve and sanitize base URL for Daily News service via TOOLCASE_GATEWAY_URL."""
    candidate = (
        (base_url.strip() if base_url else None)
        or os.environ.get("DAILY_NEWS_GATEWAY_BASE_URL")
        or os.environ.get("DAILY_NEWS_GATEWAY_URL")
        or os.environ.get("DAILY_NEWS_URL")
    )

    if not candidate:
        gw_root = os.environ.get("TOOLCASE_GATEWAY_URL", DEFAULT_TOOLCASE_GATEWAY_URL).strip().rstrip("/")
        candidate = f"{gw_root}{DEFAULT_GATEWAY_NAMESPACE}"

    candidate = candidate.strip().rstrip("/")
    # Normalize legacy port 28130 to server port 20129 if encountered
    if ":28130" in candidate:
        logger.info("Normalizing Daily News gateway port from 28130 to server port %d", DEFAULT_TOOLCASE_GATEWAY_PORT)
        candidate = candidate.replace(":28130", f":{DEFAULT_TOOLCASE_GATEWAY_PORT}")

    # Ensure /custom/daily-news namespace is present if root gateway URL was supplied
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Invalid Daily News Gateway URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError(f"Missing hostname in Daily News Gateway URL: {candidate}")

    path = parsed.path.rstrip("/")
    if not path or (not path.endswith(DEFAULT_GATEWAY_NAMESPACE) and "/custom/" not in path and "/api/" not in path):
        candidate = f"{candidate}{DEFAULT_GATEWAY_NAMESPACE}"

    return candidate


class DailyNewsGatewayClient:
    """Client for interacting with the Daily News module on Toolcase Gateway."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = REQUEST_TIMEOUT_SECS) -> None:
        self._default_base_url = base_url
        self.timeout = timeout

    def get_gateway_base_url(self, override_url: Optional[str] = None) -> str:
        """Resolve authoritative Gateway base URL."""
        return resolve_gateway_base_url(override_url or self._default_base_url)

    def check_health(self, base_url: Optional[str] = None) -> Dict[str, Any]:
        """Query GET /health (or /custom/daily-news/health) for service availability."""
        url = self.get_gateway_base_url(base_url)
        endpoints = (f"{url}/health", f"{url}/custom/daily-news/health")
        for ep in endpoints:
            try:
                req = Request(ep, headers=ACCEPT_JSON_HEADER)
                with urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.debug("Health check failed on %s: %s", ep, e)
                continue
        return {"status": "unhealthy", "module": "daily-news", "error": "Gateway unreachable"}

    def fetch_feed(
        self,
        base_url: Optional[str] = None,
        sources: Optional[Sequence[str]] = DEFAULT_SOURCES,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """Fetch latest raw news items from gateway endpoint GET /api/v1/feed."""
        gw_base = self.get_gateway_base_url(base_url)
        params: Dict[str, Any] = {"limit": limit}
        if sources:
            params["sources"] = ",".join(sources)

        query_str = urlencode(params)
        endpoint = f"{gw_base}/api/v1/feed?{query_str}"
        logger.info("Fetching latest news from gateway: %s", endpoint)

        try:
            req = Request(endpoint, headers=ACCEPT_JSON_HEADER)
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.exception("Failed fetching feed from gateway endpoint %s", endpoint)
            raise RuntimeError(f"Failed to fetch feed from Daily News Gateway at {gw_base}: {e}") from e

        raw_items: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            raw_items = data.get("items") or data.get("candidates") or []
        elif isinstance(data, list):
            raw_items = data

        return self._sanitize_and_dedupe_items(raw_items)

    def discover_candidates(
        self,
        base_url: Optional[str] = None,
        limit: int = 5,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        curated_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute tiered discovery via POST /api/v1/discover."""
        gw_base = self.get_gateway_base_url(base_url)
        endpoint = f"{gw_base}/api/v1/discover"
        payload: Dict[str, Any] = {"limit": limit}
        if from_date:
            payload["from_date"] = from_date
        if to_date:
            payload["to_date"] = to_date
        if topics:
            payload["topics"] = topics
        if sources:
            payload["sources"] = sources
        if curated_candidates:
            payload["curated_candidates"] = curated_candidates

        body_bytes = json.dumps(payload).encode("utf-8")
        req = Request(
            endpoint,
            data=body_bytes,
            headers=JSON_HEADERS,
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.exception("Failed tiered discovery from %s", endpoint)
            raise RuntimeError(f"Tiered discovery failed on Daily News Gateway: {e}") from e

    def consume_candidates(
        self,
        candidate_ids: Sequence[str],
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark candidate IDs as consumed (removal logic) via POST /api/v1/consume."""
        valid_ids = [_sanitize_log_val(cid, max_len=64) for cid in candidate_ids if str(cid).strip()]
        valid_ids = [cid for cid in valid_ids if cid]
        if not valid_ids:
            return {"status": "consumed", "count": 0}

        gw_base = self.get_gateway_base_url(base_url)
        endpoint = f"{gw_base}/api/v1/consume"
        payload = {"candidate_ids": valid_ids}
        body_bytes = json.dumps(payload).encode("utf-8")

        req = Request(
            endpoint,
            data=body_bytes,
            headers=JSON_HEADERS,
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                safe_logged = ", ".join(valid_ids[:10])
                if len(valid_ids) > 10:
                    safe_logged += f"... (+{len(valid_ids) - 10} more)"
                logger.info("Marked %d candidate(s) as consumed on gateway: [%s]", len(valid_ids), safe_logged)
                return result
        except Exception as e:
            logger.warning("Could not sync candidate removal to gateway %s: %s", endpoint, e)
            return {"status": "error", "error": str(e), "candidate_ids": valid_ids}

    def write_feed(
        self,
        base_url: Optional[str] = None,
        output: Path | str = Path("data/newsnow_feed.json"),
        minimum: int = 3,
        sources: Optional[Sequence[str]] = DEFAULT_SOURCES,
        limit: int = 30,
    ) -> int:
        """Fetch feed items from gateway and write atomically to output path."""
        items = self.fetch_feed(base_url=base_url, sources=sources, limit=limit)
        if len(items) < minimum:
            raise RuntimeError(f"News gateway returned {len(items)} valid items; need at least {minimum}")

        out_path = _resolve_safe_output_path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(out_path)
        return len(items)

    @staticmethod
    def _sanitize_and_dedupe_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate raw feed items by canonical URL and ensure required keys."""
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            url, title = _extract_item_keys(raw)
            if not url or not title:
                continue

            key = url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)

            items.append(_normalize_feed_item(raw, url))

        return items


# Clean Architecture DIP: Register default gateway adapter with domain candidate consumer port
try:
    from lib.fixed_niche.candidate_helpers import register_candidate_consumer

    register_candidate_consumer(DailyNewsGatewayClient())
except Exception as _reg_exc:
    logger.debug("Gateway client port registration skipped: %s", _reg_exc)

