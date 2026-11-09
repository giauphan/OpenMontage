"""Hybrid Tiered Content Discovery for Practical AI Agent Engineering niche.
Implements Option C: Hybrid Tiered Strategy (JEV Decision gen-dec-1793437184-00c5T6T0SyrjS1th0LsX):
1. Tier 1 (Priority): Curated candidate backlog queue (data/daily_candidates.json).
2. Tier 2 (Fallback): Automated live feed (data/newsnow_feed.json / scraper).
3. Tier 3 (Fail-Closed): NO_ELIGIBLE_TOPIC if neither tier yields in-scope evidence.
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

from lib.fixed_niche.gate import FixedNicheScopeGate, ScopeVerdict
from lib.fixed_niche.policy import LockedNichePolicy, OutcomeStatus, load_locked_policy
from lib.fixed_niche.candidate_helpers import (
    CandidateConsumerPort,
    get_registered_candidate_consumers,
    load_candidates_from_file,
    normalize_candidate_dict,
    parse_timestamp,
    register_candidate_consumer,
    sort_candidates_by_recency,
)

logger = logging.getLogger(__name__)

# Facade re-exports for backward compatibility and port definitions
__all__ = [
    "CandidateConsumerPort",
    "DiscoveryTier",
    "HybridCandidateDiscovery",
    "TieredDiscoveryResult",
    "load_candidates_from_file",
    "normalize_candidate_dict",
    "parse_timestamp",
    "register_candidate_consumer",
    "sort_candidates_by_recency",
]


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
        consumer: Optional[CandidateConsumerPort] = None,
        used_ids: Optional[Set[str]] = None,
    ) -> None:
        self.policy = policy or load_locked_policy()
        self.gate = gate or FixedNicheScopeGate(self.policy)
        self.root_dir = Path(root_dir or Path(__file__).resolve().parent.parent.parent).resolve()
        self.consumer = consumer
        self.used_ids = set(used_ids) if used_ids is not None else None

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

        # Sliding freshness window: 1 to 7 days
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
            active_and_archived = data.get("active_projects", []) + data.get("archived_projects", [])
            return {
                str(item["project_id"])
                for item in active_and_archived
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
                if not p.is_dir() or p.is_symlink():
                    continue
                if p.name.startswith("cand_") or (p / "renders").is_dir() or (p / "validation_status.json").is_file():
                    used.add(p.name)
        rec_dir = self.root_dir / "projects" / "_failed_generation_recovered"
        if rec_dir.is_dir() and not rec_dir.is_symlink():
            for rec in rec_dir.iterdir():
                if rec.is_dir() and not rec.is_symlink():
                    m = re.match(r"^([A-Za-z0-9_-]+?)_\d{8}T\d{6}Z_", rec.name)
                    used.add(m.group(1) if m else rec.name)
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
        """Record candidate ID as consumed and sync to outbound ports (DIP)."""
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

        # Synchronize candidate removal / consumption to outbound consumer ports (DIP)
        if self.consumer is not None:
            try:
                self.consumer.consume_candidates([candidate_id])
            except Exception as exc:
                logger.debug("Candidate consume sync failed on primary consumer: %s", exc)
        else:
            for c in get_registered_candidate_consumers():
                try:
                    c.consume_candidates([candidate_id])
                except Exception as exc:
                    logger.debug("Candidate consume sync failed on registered consumer: %s", exc)

    @staticmethod
    def _load_candidates_from_file(file_path: Path) -> List[Dict[str, Any]]:
        """Safely load candidates from a JSON or YAML file."""
        return load_candidates_from_file(file_path)

    def load_curated_candidates(self) -> List[Dict[str, Any]]:
        """Load candidate list from Tier 1 curated backlog file and authorized production source feeds."""
        candidates = self._load_candidates_from_file(self.curated_path)
        seen_keys = {
            str(c.get("candidate_id") or c.get("id") or c.get("canonical_url") or c.get("url"))
            for c in candidates
        }
        sources_dir = self.root_dir / "config" / "sources"
        if sources_dir.is_dir():
            for feed_file in sorted(sources_dir.glob("*.json")):
                for fc in self._load_candidates_from_file(feed_file):
                    key = str(fc.get("candidate_id") or fc.get("id") or fc.get("canonical_url") or fc.get("url"))
                    if key not in seen_keys:
                        candidates.append(fc)
                        seen_keys.add(key)
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
        return normalize_candidate_dict(cand, cid, verdict)

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
        return parse_timestamp(val)

    def sort_by_recency(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort candidates so recent/latest published items appear first."""
        return sort_candidates_by_recency(candidates)

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

    def discover_candidates(self, count: int = 1, used_ids: Optional[Set[str]] = None) -> TieredDiscoveryResult:
        """Execute Option C: Hybrid Tiered Strategy discovery.

        Tier 1 (Curated Queue) -> Tier 2 (Automated Feed) -> Fail-Closed (NO_ELIGIBLE_TOPIC).
        """
        effective_used_ids = set(used_ids) if used_ids is not None else (
            self.used_ids if self.used_ids is not None else self.get_used_project_ids()
        )
        cutoff_dt = self.reference_time - timedelta(days=self.max_age_days)
        diagnostics: Dict[str, Any] = {
            "used_ids_count": len(effective_used_ids),
            "tier_1_checked": False,
            "tier_2_checked": False,
            "require_latest_news_active": self.require_latest_news,
            "max_age_days": self.max_age_days,
            "cutoff_timestamp_utc": cutoff_dt.isoformat(),
            "reference_time_utc": self.reference_time.isoformat(),
        }

        # Step 1: Check Tier 1 Curated Backlog
        tier_1_candidates = self._discover_tier_1_curated(effective_used_ids, count, diagnostics)
        if tier_1_candidates:
            logger.info(
                "[Tier 1: Curated Queue] Selected %d candidate(s): %s",
                len(tier_1_candidates),
                [self._sanitize_log_val(c.get("candidate_id")) for c in tier_1_candidates],
            )
            return TieredDiscoveryResult(
                tier=DiscoveryTier.TIER_1_CURATED,
                status="ELIGIBLE",
                candidates=tier_1_candidates,
                source_file=str(self.curated_path),
                diagnostics=diagnostics,
            )

        # Step 2: Check Tier 2 Automated Live Feed
        tier_2_candidates = self._discover_tier_2_feed(effective_used_ids, count, diagnostics)
        if tier_2_candidates:
            logger.info(
                "[Tier 2: Automated Feed] Selected %d candidate(s): %s",
                len(tier_2_candidates),
                [self._sanitize_log_val(c.get("candidate_id")) for c in tier_2_candidates],
            )
            return TieredDiscoveryResult(
                tier=DiscoveryTier.TIER_2_AUTOMATED,
                status="ELIGIBLE",
                candidates=tier_2_candidates,
                source_file=str(self.feed_path),
                diagnostics=diagnostics,
            )

        # Step 3: Fail-Closed
        logger.warning(
            "[Tier 3: Fail-Closed] Neither Tier 1 (curated) nor Tier 2 (feed) "
            "provided eligible in-scope topics. Rejecting run without side-effects."
        )
        return TieredDiscoveryResult(
            tier=DiscoveryTier.NONE,
            status=OutcomeStatus.NO_ELIGIBLE_TOPIC.value,
            candidates=[],
            reason="Zero in-scope candidates passed deterministic gate across Tier 1 and Tier 2",
            diagnostics=diagnostics,
        )
