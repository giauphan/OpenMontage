"""Hybrid Tiered Content Discovery for Practical AI Agent Engineering niche.

Implements Option C: Hybrid Tiered Strategy (JEV Decision gen-dec-1793437184-00c5T6T0SyrjS1th0LsX):
1. Tier 1 (Priority): Curated candidate backlog queue (data/daily_candidates.json).
   - High editorial signal, verified primary docs, zero wasted render cycles.
2. Tier 2 (Fallback): Automated live feed (data/newsnow_feed.json / scraper).
   - Autonomous execution when curated backlog is empty or exhausted.
3. Tier 3 (Fail-Closed): NO_ELIGIBLE_TOPIC if neither tier yields in-scope evidence.

Target module size: < 450 lines. Clean Architecture & DDD compliant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.fixed_niche.gate import FixedNicheScopeGate
from lib.fixed_niche.policy import LockedNichePolicy, OutcomeStatus, load_locked_policy

logger = logging.getLogger(__name__)


class DiscoveryTier(str, Enum):
    TIER_1_CURATED = "tier_1_curated"
    TIER_2_AUTOMATED = "tier_2_automated"
    NONE = "none"


@dataclass
class TieredDiscoveryResult:
    """Outcome of tiered candidate discovery."""
    tier: DiscoveryTier
    status: str
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    source_file: Optional[str] = None
    reason: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_eligible(self) -> bool:
        return self.status == "ELIGIBLE" and len(self.candidates) > 0


class HybridCandidateDiscovery:
    """Manages priority-based tiered discovery with factual gating and deduplication."""

    DEFAULT_CURATED_FILE = "data/daily_candidates.json"
    DEFAULT_FEED_FILE = "data/newsnow_feed.json"
    CONSUMED_TRACKER_FILE = "data/consumed_candidates.json"

    def __init__(
        self,
        policy: Optional[LockedNichePolicy] = None,
        gate: Optional[FixedNicheScopeGate] = None,
        curated_path: Optional[Path] = None,
        feed_path: Optional[Path] = None,
        root_dir: Optional[Path] = None,
        require_latest_news: Optional[bool] = None,
        max_age_days: Optional[int] = None,
        reference_time: Optional[datetime] = None,
        strict_news_only: Optional[bool] = None,
    ) -> None:
        self.policy = policy or load_locked_policy()
        self.gate = gate or FixedNicheScopeGate(self.policy)
        self.root_dir = Path(root_dir or Path(__file__).resolve().parent.parent.parent).resolve()

        # Configurable paths with environment variable overrides
        env_curated = os.environ.get("DAILY_CANDIDATES_FILE") or os.environ.get("OPENMONTAGE_CANDIDATES_FILE")
        self.curated_path = Path(curated_path or env_curated or (self.root_dir / self.DEFAULT_CURATED_FILE)).resolve()
        
        env_feed = os.environ.get("NEWSNOW_FEED_FILE")
        self.feed_path = Path(feed_path or env_feed or (self.root_dir / self.DEFAULT_FEED_FILE)).resolve()
        
        self.tracker_path = self.root_dir / self.CONSUMED_TRACKER_FILE

        # Enforce and activate latest news discovery (default: True, active)
        if require_latest_news is not None:
            self.require_latest_news = require_latest_news
        else:
            env_latest = os.environ.get("REQUIRE_LATEST_NEWS", "1").strip().lower()
            self.require_latest_news = env_latest in ("1", "true", "yes", "on")

        # Sliding freshness window: 1 to 7 days (Tiered Hybrid: 0-3d priority, 4-7d buffer, default 7 days / 168 hours)
        if max_age_days is not None:
            self.max_age_days = max(1, int(max_age_days))
        elif os.environ.get("NEWS_MAX_AGE_DAYS"):
            self.max_age_days = max(1, int(os.environ["NEWS_MAX_AGE_DAYS"]))
        elif os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS"):
            self.max_age_days = max(1, int(float(os.environ["NEWS_MAX_SOURCE_AGE_HOURS"]) / 24.0))
        else:
            self.max_age_days = 7

        # Strict news only: if True, completely disallows evergreen explainers
        if strict_news_only is not None:
            self.strict_news_only = strict_news_only
        else:
            env_strict = os.environ.get("STRICT_NEWS_ONLY", "0").strip().lower()
            self.strict_news_only = env_strict in ("1", "true", "yes", "on")

        self.reference_time = reference_time or datetime.now(timezone.utc)

    @staticmethod
    def _sanitize_log_val(val: Any, max_len: int = 80) -> str:
        """Sanitize user/file-provided strings to prevent CRLF log injection."""
        return re.sub(r"[\r\n\t]", "_", str(val or "")).strip()[:max_len]

    def _get_scheduled_project_ids(self) -> Set[str]:
        sched_file = self.root_dir / "config" / "publish_schedule.json"
        if not sched_file.is_file():
            return set()
        try:
            data = json.loads(sched_file.read_text(encoding="utf-8"))
            return {
                str(item["project_id"])
                for item in data.get("active_projects", [])
                if isinstance(item, dict) and item.get("project_id")
            }
        except Exception as e:
            logger.debug(f"Could not parse publish_schedule.json: {e}")
            return set()

    def _get_disk_project_ids(self) -> Set[str]:
        used: Set[str] = set()
        for p_dirname in ("projects", "projects_news"):
            p_dir = self.root_dir / p_dirname
            if not p_dir.is_dir():
                continue
            for p in p_dir.iterdir():
                if not p.is_dir():
                    continue
                has_renders = (p / "renders").is_dir() and any((p / "renders").glob("*.mp4"))
                is_validated = (p / "validation_status.json").is_file()
                if has_renders or is_validated:
                    used.add(p.name)
        return used

    def _get_consumed_project_ids(self) -> Set[str]:
        if not self.tracker_path.is_file():
            return set()
        try:
            t_data = json.loads(self.tracker_path.read_text(encoding="utf-8"))
            return {str(cid) for cid in t_data.get("consumed_ids", [])}
        except Exception as e:
            logger.debug(f"Could not parse consumed_candidates.json: {e}")
            return set()

    def get_used_project_ids(self) -> Set[str]:
        """Aggregate all used or in-progress candidate/project IDs across storage."""
        return self._get_scheduled_project_ids() | self._get_disk_project_ids() | self._get_consumed_project_ids()

    def mark_candidate_consumed(self, candidate_id: str) -> None:
        """Record candidate ID as consumed so it is not re-selected on subsequent runs."""
        if not candidate_id:
            return
        consumed: List[str] = []
        if self.tracker_path.is_file():
            try:
                data = json.loads(self.tracker_path.read_text(encoding="utf-8"))
                consumed = list(data.get("consumed_ids", []))
            except Exception:
                consumed = []

        if candidate_id not in consumed:
            consumed.append(candidate_id)
            self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "consumed_ids": consumed,
            }
            self.tracker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            safe_id = self._sanitize_log_val(candidate_id)
            logger.info("Marked candidate '%s' as consumed in %s", safe_id, self.tracker_path)

    @staticmethod
    def _load_candidates_from_file(file_path: Path) -> List[Dict[str, Any]]:
        """Safely load candidates from a JSON or YAML file."""
        if not file_path.is_file():
            return []
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return []
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

    def load_curated_candidates(self) -> List[Dict[str, Any]]:
        """Load candidate list from Tier 1 curated backlog file and production source feed."""
        candidates = self._load_candidates_from_file(self.curated_path)
        if not candidates:
            prod_feed = self.root_dir / "config" / "sources" / "production_agent_engineering_feed.json"
            if prod_feed.is_file():
                candidates = self._load_candidates_from_file(prod_feed)
        return candidates

    def load_automated_feed_candidates(self) -> List[Dict[str, Any]]:
        """Load candidate list from Tier 2 automated feed file."""
        return self._load_candidates_from_file(self.feed_path)

    def _is_candidate_eligible(
        self,
        cand: Dict[str, Any],
        cid: str,
        used_ids: Set[str],
        cutoff_dt: datetime,
    ) -> Tuple[bool, Optional[ScopeVerdict]]:
        """Evaluate whether a candidate passes niche gate, deduplication, and freshness cutoff."""
        if not cid or cid in used_ids:
            return False, None

        verdict = self.gate.evaluate_candidate(cand)
        if not verdict.is_eligible:
            safe_cid = self._sanitize_log_val(cid)
            logger.debug("Candidate %s rejected by FixedNicheScopeGate: %s", safe_cid, verdict.reason)
            return False, None

        content_kind = verdict.content_kind or cand.get("content_kind", "evergreen_explainer")
        is_evergreen = bool(cand.get("is_evergreen", content_kind == "evergreen_explainer"))

        if self.strict_news_only and is_evergreen:
            safe_cid = self._sanitize_log_val(cid)
            logger.info("Candidate %s rejected: strict_news_only is active and candidate is evergreen", safe_cid)
            return False, None

        if self.require_latest_news and not is_evergreen:
            pub_raw = cand.get("published_at") or cand.get("published_at_utc")
            pub_ts = self.parse_timestamp(pub_raw)
            if pub_ts > 0.0:
                cand_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                if cand_dt < cutoff_dt:
                    safe_cid = self._sanitize_log_val(cid)
                    safe_pub = self._sanitize_log_val(pub_raw)
                    logger.info(
                        "Candidate %s published at %s is older than max_age_days=%d (cutoff: %s). Skipping stale topic.",
                        safe_cid, safe_pub, self.max_age_days, cutoff_dt.isoformat()
                    )
                    return False, None

        return True, verdict

    def _normalize_candidate_dict(
        self,
        cand: Dict[str, Any],
        cid: str,
        verdict: ScopeVerdict,
    ) -> Dict[str, Any]:
        """Normalize an eligible candidate into a uniform dictionary representation."""
        content_kind = verdict.content_kind or cand.get("content_kind", "evergreen_explainer")
        normalized = dict(cand)
        normalized["candidate_id"] = cid
        normalized["id"] = cid
        normalized["topic_family"] = verdict.topic_family
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

    def filter_and_validate_candidates(
        self,
        candidates: List[Dict[str, Any]],
        used_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Filter out already used IDs, stale dates, and validate against FixedNicheScopeGate."""
        cutoff_dt = self.reference_time - timedelta(days=self.max_age_days)
        valid: List[Dict[str, Any]] = []
        for cand in candidates:
            cid = str(cand.get("candidate_id") or cand.get("id") or "")
            if not cid:
                seed = str(cand.get("title", "")) + str(cand.get("canonical_url") or cand.get("url") or "")
                cid = f"cand_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
                cand["candidate_id"] = cid
            is_ok, verdict = self._is_candidate_eligible(cand, cid, used_ids, cutoff_dt)
            if is_ok and verdict:
                valid.append(self._normalize_candidate_dict(cand, cid, verdict))
        return valid

    @staticmethod
    def parse_timestamp(val: Any) -> float:
        """Parse ISO timestamp or date into float epoch seconds."""
        if not val:
            return 0.0
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).strip().replace("Z", "+00:00")
            if "T" in s:
                dt = datetime.fromisoformat(s)
            elif "-" in s:
                parts = [int(p) for p in s.split("-")]
                dt = datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
            elif "/" in s:
                parts = [int(p) for p in s.split("/")]
                if parts[0] > 1000:
                    dt = datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
                else:
                    dt = datetime(parts[2], parts[1], parts[0], tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    def sort_by_recency(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort candidates so recent/latest published items appear first.

        Breaking news items with real published dates take priority over evergreen explainers.
        Items without explicit dates preserve their original backlog insertion order.
        """
        def recency_key(pair: Tuple[int, Dict[str, Any]]) -> Tuple[int, int, float, int]:
            idx, item = pair
            is_news = 1 if (item.get("content_kind") == "news" and not item.get("is_evergreen")) else 0
            has_date = 1 if item.get("has_explicit_date") else 0
            ts = self.parse_timestamp(item.get("published_at_utc")) if has_date else 0.0
            return (is_news, has_date, ts, -idx)

        sorted_indexed = sorted(enumerate(candidates), key=recency_key, reverse=True)
        return [item for _, item in sorted_indexed]

    def _discover_tier_1_curated(
        self,
        used_ids: Set[str],
        count: int,
        diagnostics: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """Ingest and validate candidate queue from Tier 1 curated backlog."""
        diagnostics["tier_1_checked"] = True
        raw_curated = self.load_curated_candidates()
        diagnostics["tier_1_raw_count"] = len(raw_curated)
        if not raw_curated:
            return None

        valid_curated = self.filter_and_validate_candidates(raw_curated, used_ids)
        diagnostics["tier_1_valid_count"] = len(valid_curated)
        if not valid_curated:
            logger.info(
                "[Tier 1: Curated Queue] Backlog file exists (%d items), "
                "but all candidates are already used or off-niche. Cascading to Tier 2.",
                len(raw_curated)
            )
            return None

        if self.require_latest_news:
            valid_curated = self.sort_by_recency(valid_curated)
        return valid_curated[:count]

    def _discover_tier_2_feed(
        self,
        used_ids: Set[str],
        count: int,
        diagnostics: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """Ingest and validate candidate queue from Tier 2 automated feed."""
        diagnostics["tier_2_checked"] = True
        raw_feed = self.load_automated_feed_candidates()
        diagnostics["tier_2_raw_count"] = len(raw_feed)
        if not raw_feed:
            return None

        valid_feed = self.filter_and_validate_candidates(raw_feed, used_ids)
        diagnostics["tier_2_valid_count"] = len(valid_feed)
        if not valid_feed:
            return None

        if self.require_latest_news:
            valid_feed = self.sort_by_recency(valid_feed)

        try:
            from lib.fixed_niche.ranker import FixedNicheTopicScorer
            scored_pairs = [(c, self.gate.evaluate_candidate(c)) for c in valid_feed]
            ranked = FixedNicheTopicScorer().rank_candidates(scored_pairs)
            if ranked:
                valid_feed = ranked
        except Exception as e:
            logger.debug(f"Optional topic ranking skipped: {e}")

        return valid_feed[:count]

    def discover_candidates(self, count: int = 1) -> TieredDiscoveryResult:
        """Execute Option C: Hybrid Tiered Strategy discovery.

        Tier 1 (Curated Queue) -> Tier 2 (Automated Feed) -> Fail-Closed (NO_ELIGIBLE_TOPIC).
        """
        used_ids = self.get_used_project_ids()
        cutoff_dt = self.reference_time - timedelta(days=self.max_age_days)
        diagnostics: Dict[str, Any] = {
            "used_ids_count": len(used_ids),
            "tier_1_checked": False,
            "tier_2_checked": False,
            "require_latest_news_active": self.require_latest_news,
            "max_age_days": self.max_age_days,
            "reference_time": self.reference_time.isoformat(),
            "cutoff_date": cutoff_dt.isoformat(),
        }

        # --- TIER 1: Curated Backlog ---
        selected_t1 = self._discover_tier_1_curated(used_ids, count, diagnostics)
        if selected_t1:
            logger.info(
                "[Tier 1: Curated Queue] Selected %d in-scope candidate(s) from %s (require_latest_news=%s)",
                len(selected_t1), self.curated_path, self.require_latest_news
            )
            return TieredDiscoveryResult(
                tier=DiscoveryTier.TIER_1_CURATED,
                status="ELIGIBLE",
                candidates=selected_t1,
                source_file=str(self.curated_path),
                diagnostics=diagnostics,
            )

        # --- TIER 2: Automated Live Feed Fallback ---
        selected_t2 = self._discover_tier_2_feed(used_ids, count, diagnostics)
        if selected_t2:
            logger.info(
                "[Tier 2: Automated Feed] Selected %d in-scope candidate(s) from %s (require_latest_news=%s)",
                len(selected_t2), self.feed_path, self.require_latest_news
            )
            return TieredDiscoveryResult(
                tier=DiscoveryTier.TIER_2_AUTOMATED,
                status="ELIGIBLE",
                candidates=selected_t2,
                source_file=str(self.feed_path),
                diagnostics=diagnostics,
            )

        # --- TIER 3: Clean Fail-Closed ---
        logger.warning(
            "STATUS=NO_ELIGIBLE_TOPIC: Neither Tier 1 (Curated Backlog) nor Tier 2 (Automated Feed) "
            "provided an eligible in-scope topic with verified evidence."
        )
        return TieredDiscoveryResult(
            tier=DiscoveryTier.NONE,
            status=OutcomeStatus.NO_ELIGIBLE_TOPIC.value,
            candidates=[],
            reason="Zero in-scope candidates passed deterministic gate across Tier 1 and Tier 2",
            diagnostics=diagnostics,
        )
