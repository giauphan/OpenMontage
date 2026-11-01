"""Bounded source adapter for the Practical AI Agent Engineering locked niche.

Handles:
- Primary evidence: Official documentation, specifications (MCP, LSP), GitHub releases, repository sources.
- Technical mechanisms: Vendor changelogs, RFCs, arXiv papers.
- Community signals: Hacker News, Reddit, Stack Overflow (used only as question/demand signals, never sole proof).
- SSRF-safety: enforces HTTPS, allowed domains, disallows private IP ranges.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from tools.news.newsnow_adapter import NewsNowAdapter


ALLOWED_PRIMARY_DOMAINS = {
    "docs.anthropic.com",
    "docs.github.com",
    "modelcontextprotocol.io",
    "microsoft.github.io",
    "openai.com",
    "arxiv.org",
    "github.com",
    "git-scm.com",
    "tree-sitter.github.io",
    "docs.docker.com",
    "docs.pytest.org",
    "langchain.com",
}

COMMUNITY_SIGNAL_DOMAINS = {
    "news.ycombinator.com",
    "reddit.com",
    "stackoverflow.com",
}

TOPIC_FAMILY_CANONICAL_MAP = {
    "context_memory": "context_memory",
    "tool_calling": "agent_tool_use",
    "agent_tool_use": "agent_tool_use",
    "debugging_reliability": "debugging_reliability",
    "benchmarking_evaluation": "agent_evaluation",
    "agent_evaluation": "agent_evaluation",
    "agent_architecture": "agent_architecture",
}


@dataclass(frozen=True)
class NormalizedSourceItem:
    """Normalized source item conforming to the news candidate contract."""
    source_id: str
    canonical_url: str
    title: str
    body: str
    publisher: str
    source_type: str  # vendor_doc, release, specification, paper, community_signal
    published_at_utc: Optional[str]
    content_hash: str
    is_evergreen: bool
    license_permission: str
    source_snapshot: Optional[str] = None
    snapshot_sha256: Optional[str] = None
    topic_family: Optional[str] = None
    symptom: Optional[str] = None
    root_cause: Optional[str] = None
    remedy: Optional[str] = None
    evidence_excerpt: Optional[str] = None
    independent_fact_check: Optional[Dict[str, Any]] = None


class FixedNicheSourceAdapter:
    """Bounded, SSRF-safe source adapter for agent engineering topics."""

    def __init__(self, allowed_domains: Optional[Set[str]] = None):
        self.allowed_domains = allowed_domains or (ALLOWED_PRIMARY_DOMAINS | COMMUNITY_SIGNAL_DOMAINS)
        self._newsnow_adapter = NewsNowAdapter()

    def is_safe_url(self, url: str) -> bool:
        """SSRF protection: enforce https, valid hostname, not a private IP."""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() != "https":
                return False
            host = parsed.hostname.lower() if parsed.hostname else ""
            if not host:
                return False

            # Check if host is raw IP and forbid private ranges
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    return False
            except ValueError:
                pass

            # Check against allowed domain suffixes
            return any(host == d or host.endswith("." + d) for d in self.allowed_domains)
        except Exception:
            return False

    def normalize_source_item(self, raw_item: Dict[str, Any]) -> Optional[NormalizedSourceItem]:
        """Validate and normalize raw source item into a canonical structure."""
        url = str(raw_item.get("url") or raw_item.get("canonical_url") or "").strip()
        if not self.is_safe_url(url):
            return None

        canonical_url = self._newsnow_adapter.canonicalize_url(url)
        title = str(raw_item.get("title") or "").strip()
        body = str(raw_item.get("body") or raw_item.get("summary") or "").strip()
        if not title:
            return None

        publisher = str(raw_item.get("publisher") or raw_item.get("source") or "Unknown")
        source_type = str(raw_item.get("source_type") or "vendor_doc")

        pub_at = raw_item.get("published_at") or raw_item.get("published_at_utc")
        pub_utc = None
        if pub_at:
            try:
                pub_utc = self._newsnow_adapter.parse_iso_utc(str(pub_at))
            except Exception:
                pub_utc = None

        content_h = self._newsnow_adapter.compute_content_hash(title, body, canonical_url)
        sid = f"src_{content_h[:16]}"
        is_evergreen = bool(raw_item.get("is_evergreen", pub_utc is None))

        snap = raw_item.get("source_snapshot")
        snap_sha = raw_item.get("snapshot_sha256")
        if snap and not snap_sha:
            snap_sha = hashlib.sha256(str(snap).encode("utf-8")).hexdigest()

        return NormalizedSourceItem(
            source_id=sid,
            canonical_url=canonical_url,
            title=title,
            body=body,
            publisher=publisher,
            source_type=source_type,
            published_at_utc=pub_utc,
            content_hash=content_h,
            is_evergreen=is_evergreen,
            license_permission=str(raw_item.get("license_permission") or "public_documentation"),
            source_snapshot=str(snap) if snap else None,
            snapshot_sha256=str(snap_sha) if snap_sha else None,
            topic_family=TOPIC_FAMILY_CANONICAL_MAP.get(str(raw_item.get("topic_family")).lower(), raw_item.get("topic_family")),
            symptom=raw_item.get("symptom"),
            root_cause=raw_item.get("root_cause"),
            remedy=raw_item.get("remedy"),
            evidence_excerpt=raw_item.get("evidence_excerpt"),
            independent_fact_check=raw_item.get("independent_fact_check"),
        )

    def to_candidate_dict(self, item: NormalizedSourceItem) -> Dict[str, Any]:
        """Convert normalized source item to a standard pipeline candidate dictionary."""
        d = {
            "candidate_id": f"cand_{item.content_hash[:16]}",
            "id": f"cand_{item.content_hash[:16]}",
            "canonical_url": item.canonical_url,
            "original_url": item.canonical_url,
            "url": item.canonical_url,
            "title": item.title,
            "body": item.body,
            "summary": item.body[:300],
            "publisher": item.publisher,
            "normalized_publisher": item.publisher.lower(),
            "published_at_utc": item.published_at_utc,
            "published_at": item.published_at_utc,
            "content_hash": item.content_hash,
            "source_type": item.source_type,
            "is_evergreen": item.is_evergreen,
            "content_kind": "evergreen_explainer" if item.is_evergreen else "news",
        }
        if item.topic_family:
            d["topic_family"] = TOPIC_FAMILY_CANONICAL_MAP.get(item.topic_family.lower(), item.topic_family)
        if item.source_snapshot:
            d["source_snapshot"] = item.source_snapshot
        if item.snapshot_sha256:
            d["snapshot_sha256"] = item.snapshot_sha256
        if item.symptom:
            d["symptom"] = item.symptom
        if item.root_cause:
            d["root_cause"] = item.root_cause
        if item.remedy:
            d["remedy"] = item.remedy
        if item.evidence_excerpt:
            d["evidence_excerpt"] = item.evidence_excerpt
        if item.independent_fact_check:
            d["independent_fact_check"] = item.independent_fact_check
        return d

    def _resolve_feed_paths(self, sources_feed_path: Optional[Path] = None) -> List[Path]:
        """Resolve production feed paths according to configuration."""
        if sources_feed_path:
            return [Path(sources_feed_path)]

        paths: List[Path] = []
        curated_feed = Path("data/daily_candidates.json")
        if curated_feed.is_file():
            paths.append(curated_feed)
        default_feed = Path("config/sources/production_agent_engineering_feed.json")
        if default_feed.is_file():
            paths.append(default_feed)
        return paths

    def _parse_feed_items(self, fp: Path) -> List[Dict[str, Any]]:
        """Parse raw candidate feed file into candidate dictionaries."""
        if not fp.is_file():
            return []
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw_items = data.get("items", [])
            elif isinstance(data, list):
                raw_items = data
            else:
                raw_items = []
            candidates: List[Dict[str, Any]] = []
            for raw in raw_items:
                norm = self.normalize_source_item(raw)
                if norm:
                    candidates.append(self.to_candidate_dict(norm))
            return candidates
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed parsing production feed %s: %s", fp, e)
            return []

    def discover_production_candidates(
        self,
        sources_feed_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Discover production candidates from official feeds without test fixture pollution.

        Reads from authorized primary feeds or an explicit sources_feed_path.
        Returns an empty list if no primary production feeds are configured.
        """
        feed_paths = self._resolve_feed_paths(sources_feed_path)
        candidates: List[Dict[str, Any]] = []
        for fp in feed_paths:
            candidates.extend(self._parse_feed_items(fp))
        return candidates
