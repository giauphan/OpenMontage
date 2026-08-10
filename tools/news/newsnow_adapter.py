"""NewsNow Feed Adapter and Data Normalizer.

Transforms raw input JSON/dict items into strictly normalized candidates.
Deduplicates by content hash, normalizes URLs/publishers/timestamps, and filters stale items.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from jsonschema import Draft202012Validator


class NewsNowAdapter:
    """Adapter for ingesting, canonicalizing, and deduplicating NewsNow payloads."""

    VERSION: str = "1.0.0"

    def __init__(
        self,
        raw_schema_path: Optional[Union[str, Path]] = None,
        normalized_schema_path: Optional[Union[str, Path]] = None,
        freshness_window_hours: float = 48.0,
    ) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.raw_schema_path = Path(raw_schema_path) if raw_schema_path else base_dir / "schemas/news/raw_news_item.schema.json"
        self.normalized_schema_path = Path(normalized_schema_path) if normalized_schema_path else base_dir / "schemas/news/normalized_news_candidate.schema.json"
        self.freshness_window_hours = freshness_window_hours

        self._raw_validator = self._load_validator(self.raw_schema_path)
        self._normalized_validator = self._load_validator(self.normalized_schema_path)

    @staticmethod
    def _load_validator(path: Path) -> Draft202012Validator:
        with path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        return Draft202012Validator(schema)

    @staticmethod
    def canonicalize_url(url: str) -> str:
        """Strip tracking query params, lower scheme/host, remove trailing slash."""
        if not url:
            return ""
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        if not path:
            path = ""

        # Filter out common tracking query parameters
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "fbclid", "gclid", "msclkid", "ref", "source", "rss"
        }
        query_dict = parse_qs(parsed.query, keep_blank_values=False)
        filtered_query = {
            k: v for k, v in query_dict.items() if k.lower() not in tracking_params
        }
        new_query = urlencode(filtered_query, doseq=True)

        return urlunparse((scheme, netloc, path, parsed.params, new_query, ""))

    @staticmethod
    def normalize_publisher(publisher: Optional[str]) -> str:
        """Clean and normalize publisher name."""
        if not publisher:
            return "Unknown"
        pub = publisher.strip()
        pub = re.sub(r"\s+", " ", pub)
        # Strip common trailing domain TLDs if present like "Example.com" -> "Example"
        pub_clean = re.sub(r"\.(com|org|net|co|io|gov|news)$", "", pub, flags=re.IGNORECASE)
        return pub_clean.strip() or "Unknown"

    @staticmethod
    def parse_iso_utc(ts_str: str) -> str:
        """Parse raw timestamp string and output ISO-8601 UTC string."""
        ts_str = ts_str.strip()
        # Handle trailing Z
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"

        dt = None
        try:
            dt = datetime.datetime.fromisoformat(ts_str)
        except ValueError:
            # Fallback parsing common formats
            for fmt in (
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.datetime.strptime(ts_str, fmt)
                    break
                except ValueError:
                    pass

        if dt is None:
            raise ValueError(f"Invalid timestamp format: {ts_str}")

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)

        return dt.isoformat()

    @staticmethod
    def compute_title_hash(title: str) -> str:
        """SHA-256 hash of normalized title."""
        norm = re.sub(r"\s+", " ", title.strip().lower())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_content_hash(title: str, body: Optional[str], canonical_url: str) -> str:
        """SHA-256 hash of combined title, canonical URL, and body signature."""
        clean_title = re.sub(r"\s+", " ", title.strip().lower())
        clean_url = canonical_url.strip().lower()
        clean_body = re.sub(r"\s+", " ", (body or "").strip().lower())
        payload = f"{clean_title}|{clean_url}|{clean_body[:500]}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def normalize_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Validate raw item and return normalized candidate dict."""
        self._raw_validator.validate(raw_item)

        raw_id = str(raw_item["id"])
        orig_url = str(raw_item["url"])
        title = str(raw_item["title"]).strip()
        pub = str(raw_item.get("publisher") or "Unknown")
        published_at_raw = str(raw_item["published_at"])
        body = str(raw_item.get("body") or "")
        desc = str(raw_item.get("description") or "")

        canonical_url = self.canonicalize_url(orig_url)
        norm_pub = self.normalize_publisher(pub)
        pub_utc = self.parse_iso_utc(published_at_raw)
        title_h = self.compute_title_hash(title)
        content_h = self.compute_content_hash(title, body or desc, canonical_url)

        candidate_id = f"cand_{content_h[:16]}"

        raw_provenance = {
            "source_id": raw_id,
            "source_feed": raw_item.get("source_feed") or "newsnow",
        }
        if "extra" in raw_item and isinstance(raw_item["extra"], dict):
            raw_provenance["extra"] = raw_item["extra"]

        candidate: Dict[str, Any] = {
            "candidate_id": candidate_id,
            "canonical_url": canonical_url,
            "original_url": orig_url,
            "title": title,
            "publisher": pub,
            "normalized_publisher": norm_pub,
            "published_at_utc": pub_utc,
            "content_hash": content_h,
            "title_hash": title_h,
            "raw_provenance": raw_provenance,
            "adapter_version": self.VERSION,
        }

        if raw_item.get("author"):
            candidate["author"] = str(raw_item["author"])
        if desc:
            candidate["description"] = desc
        if body:
            candidate["body"] = body
        if raw_item.get("tags") and isinstance(raw_item["tags"], list):
            candidate["tags"] = [str(t) for t in raw_item["tags"]]
        if raw_item.get("language"):
            candidate["language"] = str(raw_item["language"])
        if raw_item.get("image_url"):
            candidate["image_url"] = str(raw_item["image_url"])

        self._normalized_validator.validate(candidate)
        return candidate

    def ingest_and_normalize(
        self,
        raw_items: List[Dict[str, Any]],
        reference_time: Optional[datetime.datetime] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Normalize a list of items, deduplicate by content/title hash, and filter stale items."""
        if reference_time is None:
            reference_time = datetime.datetime.now(datetime.timezone.utc)
        elif reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=datetime.timezone.utc)

        cutoff = reference_time - datetime.timedelta(hours=self.freshness_window_hours)

        seen_content_hashes = set()
        seen_title_hashes = set()
        normalized_list = []
        diagnostics = []

        for item in raw_items:
            try:
                candidate = self.normalize_item(item)
            except Exception as e:
                # Capture structured diagnostic for failures
                raw_id = item.get("id", "missing_id")
                diagnostic = {
                    "raw_item_id": raw_id,
                    "reason": "invalid_format",
                    "error": str(e)
                }

                # Try to extract published_at if it's what failed
                if "timestamp" in str(e).lower() or "published_at" in str(e).lower():
                    diagnostic["field"] = "published_at"
                    diagnostic["raw_value"] = item.get("published_at", "missing")
                    diagnostic["reason"] = "invalid_iso_timestamp"

                diagnostics.append(diagnostic)
                continue

            # Deduplication check
            c_hash = candidate["content_hash"]
            t_hash = candidate["title_hash"]
            if c_hash in seen_content_hashes or t_hash in seen_title_hashes:
                continue

            # Freshness check
            item_dt = datetime.datetime.fromisoformat(candidate["published_at_utc"])
            if item_dt < cutoff:
                continue

            seen_content_hashes.add(c_hash)
            seen_title_hashes.add(t_hash)
            normalized_list.append(candidate)

        return normalized_list, diagnostics
