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
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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
    ) -> None:
        self.policy = policy or load_locked_policy()
        self.gate = gate or FixedNicheScopeGate(self.policy)
        self.root_dir = Path(root_dir or Path.cwd()).resolve()

        # Configurable paths with environment variable overrides
        env_curated = os.environ.get("DAILY_CANDIDATES_FILE") or os.environ.get("OPENMONTAGE_CANDIDATES_FILE")
        self.curated_path = Path(curated_path or env_curated or (self.root_dir / self.DEFAULT_CURATED_FILE)).resolve()
        
        env_feed = os.environ.get("NEWSNOW_FEED_FILE")
        self.feed_path = Path(feed_path or env_feed or (self.root_dir / self.DEFAULT_FEED_FILE)).resolve()
        
        self.tracker_path = self.root_dir / self.CONSUMED_TRACKER_FILE

    def get_used_project_ids(self) -> Set[str]:
        """Aggregate all used or in-progress candidate/project IDs across storage."""
        used_ids: Set[str] = set()

        # 1. Scheduled / active projects in publish_schedule.json
        sched_file = self.root_dir / "config" / "publish_schedule.json"
        if sched_file.is_file():
            try:
                data = json.loads(sched_file.read_text(encoding="utf-8"))
                for item in data.get("active_projects", []):
                    if isinstance(item, dict) and item.get("project_id"):
                        used_ids.add(str(item["project_id"]))
            except Exception as e:
                logger.debug(f"Could not parse publish_schedule.json: {e}")

        # 2. Existing rendered or validated projects on disk
        for p_dirname in ("projects", "projects_news"):
            p_dir = self.root_dir / p_dirname
            if p_dir.is_dir():
                for p in p_dir.iterdir():
                    if p.is_dir():
                        has_renders = (p / "renders").is_dir() and any((p / "renders").glob("*.mp4"))
                        is_validated = (p / "validation_status.json").is_file()
                        if has_renders or is_validated:
                            used_ids.add(p.name)

        # 3. Explicitly tracked consumed candidate IDs
        if self.tracker_path.is_file():
            try:
                t_data = json.loads(self.tracker_path.read_text(encoding="utf-8"))
                for cid in t_data.get("consumed_ids", []):
                    used_ids.add(str(cid))
            except Exception as e:
                logger.debug(f"Could not parse consumed_candidates.json: {e}")

        return used_ids

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
            logger.info(f"Marked candidate '{candidate_id}' as consumed in {self.tracker_path}")

    def load_curated_candidates(self) -> List[Dict[str, Any]]:
        """Load candidate list from Tier 1 curated backlog file."""
        if not self.curated_path.is_file():
            return []
        try:
            content = self.curated_path.read_text(encoding="utf-8")
            if not content.strip():
                return []
            if self.curated_path.suffix in (".yaml", ".yml"):
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
            logger.warning(f"Failed loading curated candidates from {self.curated_path}: {e}")
            return []

    def load_automated_feed_candidates(self) -> List[Dict[str, Any]]:
        """Load candidate list from Tier 2 automated feed file."""
        if not self.feed_path.is_file():
            return []
        try:
            content = self.feed_path.read_text(encoding="utf-8")
            if not content.strip():
                return []
            raw = json.loads(content)
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict):
                return raw.get("items", []) or raw.get("candidates", [])
            return []
        except Exception as e:
            logger.warning(f"Failed loading automated feed candidates from {self.feed_path}: {e}")
            return []

    def filter_and_validate_candidates(
        self,
        candidates: List[Dict[str, Any]],
        used_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Filter out already used IDs and validate against FixedNicheScopeGate."""
        valid: List[Dict[str, Any]] = []
        for cand in candidates:
            cid = str(cand.get("candidate_id") or cand.get("id") or "")
            if not cid or cid in used_ids:
                continue

            verdict = self.gate.evaluate_candidate(cand)
            if verdict.is_eligible:
                normalized = dict(cand)
                normalized["candidate_id"] = cid
                normalized["id"] = cid
                normalized["topic_family"] = verdict.topic_family
                normalized["content_kind"] = verdict.content_kind or cand.get("content_kind", "evergreen_explainer")
                if not normalized.get("published_at_utc"):
                    normalized["published_at_utc"] = cand.get("published_at") or datetime.now(timezone.utc).isoformat()
                if not normalized.get("published_at"):
                    normalized["published_at"] = normalized["published_at_utc"]
                if not normalized.get("normalized_publisher"):
                    normalized["normalized_publisher"] = str(cand.get("publisher") or "unknown").lower()
                if not normalized.get("publisher"):
                    normalized["publisher"] = cand.get("normalized_publisher") or "Unknown"
                if not normalized.get("url"):
                    normalized["url"] = cand.get("canonical_url") or ""
                if not normalized.get("canonical_url"):
                    normalized["canonical_url"] = normalized["url"]
                if not normalized.get("body"):
                    normalized["body"] = cand.get("summary") or cand.get("description") or ""
                if not normalized.get("summary"):
                    normalized["summary"] = normalized["body"][:300]
                valid.append(normalized)
            else:
                logger.debug(f"Candidate {cid} rejected by FixedNicheScopeGate: {verdict.reason}")
        return valid

    def discover_candidates(self, count: int = 1) -> TieredDiscoveryResult:
        """Execute Option C: Hybrid Tiered Strategy discovery.

        Tier 1 (Curated Queue) -> Tier 2 (Automated Feed) -> Fail-Closed (NO_ELIGIBLE_TOPIC).
        """
        used_ids = self.get_used_project_ids()
        diagnostics: Dict[str, Any] = {
            "used_ids_count": len(used_ids),
            "tier_1_checked": False,
            "tier_2_checked": False,
        }

        # --- TIER 1: Curated Backlog ---
        diagnostics["tier_1_checked"] = True
        raw_curated = self.load_curated_candidates()
        diagnostics["tier_1_raw_count"] = len(raw_curated)

        if raw_curated:
            valid_curated = self.filter_and_validate_candidates(raw_curated, used_ids)
            diagnostics["tier_1_valid_count"] = len(valid_curated)
            if valid_curated:
                selected = valid_curated[:count]
                logger.info(
                    f"[Tier 1: Curated Queue] Selected {len(selected)} in-scope candidate(s) "
                    f"from {self.curated_path}"
                )
                return TieredDiscoveryResult(
                    tier=DiscoveryTier.TIER_1_CURATED,
                    status="ELIGIBLE",
                    candidates=selected,
                    source_file=str(self.curated_path),
                    diagnostics=diagnostics,
                )
            else:
                logger.info(
                    f"[Tier 1: Curated Queue] Backlog file exists ({len(raw_curated)} items), "
                    "but all candidates are already used or off-niche. Cascading to Tier 2."
                )

        # --- TIER 2: Automated Live Feed Fallback ---
        diagnostics["tier_2_checked"] = True
        raw_feed = self.load_automated_feed_candidates()
        diagnostics["tier_2_raw_count"] = len(raw_feed)

        if raw_feed:
            valid_feed = self.filter_and_validate_candidates(raw_feed, used_ids)
            diagnostics["tier_2_valid_count"] = len(valid_feed)
            if valid_feed:
                # Rank candidates by editorial signal if scorer is available
                try:
                    from lib.fixed_niche.ranker import FixedNicheTopicScorer
                    scored_pairs = [(c, self.gate.evaluate_candidate(c)) for c in valid_feed]
                    ranked = FixedNicheTopicScorer().rank_candidates(scored_pairs)
                    if ranked:
                        valid_feed = ranked
                except Exception as e:
                    logger.debug(f"Optional topic ranking skipped: {e}")

                selected = valid_feed[:count]
                logger.info(
                    f"[Tier 2: Automated Feed] Selected {len(selected)} in-scope candidate(s) "
                    f"from {self.feed_path}"
                )
                return TieredDiscoveryResult(
                    tier=DiscoveryTier.TIER_2_AUTOMATED,
                    status="ELIGIBLE",
                    candidates=selected,
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
