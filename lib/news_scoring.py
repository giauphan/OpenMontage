"""Deterministic scoring for normalized news candidates.

Scores candidates along six primary axes to rank and filter them before bounded LLM selection.
Reuses pattern from lib/scoring.py (explainable float scores, stable tie-breaking).
"""

import datetime
from typing import Any, Dict, List, Tuple


class NewsCandidateScorer:
    """Scores normalized news candidates deterministically."""

    # Publisher authority tiers (higher is better)
    TIER_1_PUBLISHERS = {"reuters", "ap", "bloomberg", "wsj", "ft", "nytimes", "washingtonpost"}
    TIER_2_PUBLISHERS = {"theverge", "techcrunch", "wired", "arstechnica", "bbc", "npr", "cnbc", "guardian"}

    # Keyword matches for visualizable content (images, charts, UI, physical objects)
    VISUAL_KEYWORDS = {"chart", "graph", "photo", "video", "announced", "design", "prototype", "revealed", "leaked", "interface", "hardware"}

    # Keyword matches for high audience interest (Tech & AI focused)
    INTEREST_KEYWORDS = {
        "ai", "artificial intelligence", "tech", "technology", "software", "hardware",
        "robot", "robotics", "machine learning", "deep learning", "llm", "model",
        "gpt", "claude", "gemini", "openai", "google", "microsoft", "apple", "nvidia",
        "chip", "semiconductor", "cyber", "security", "code", "coding", "developer",
        "app", "application", "data", "computing", "algorithm", "startup", "web",
        "digital", "cloud", "quantum", "browser", "linux", "open-source", "git", "api"
    }

    def __init__(self, reference_time: datetime.datetime | None = None) -> None:
        if reference_time is None:
            self.reference_time = datetime.datetime.now(datetime.timezone.utc)
        else:
            self.reference_time = reference_time
            if self.reference_time.tzinfo is None:
                self.reference_time = self.reference_time.replace(tzinfo=datetime.timezone.utc)

    def score_freshness(self, dt: datetime.datetime) -> float:
        """Score based on time since publication (decay curve).
        0-2 hours: 1.0
        2-12 hours: linear decay to 0.5
        12-24 hours: linear decay to 0.2
        >24 hours: 0.1
        """
        age_hours = (self.reference_time - dt).total_seconds() / 3600.0
        if age_hours <= 2.0:
            return 1.0
        elif age_hours <= 12.0:
            return 1.0 - 0.5 * ((age_hours - 2.0) / 10.0)
        elif age_hours <= 24.0:
            return 0.5 - 0.3 * ((age_hours - 12.0) / 12.0)
        else:
            return 0.1

    def score_publisher(self, norm_pub: str) -> float:
        """Score based on publisher authority tier."""
        p = norm_pub.lower()
        if p in self.TIER_1_PUBLISHERS:
            return 1.0
        elif p in self.TIER_2_PUBLISHERS:
            return 0.8
        elif p != "unknown":
            return 0.5
        else:
            return 0.2

    def score_fact_density(self, title: str, body: str) -> float:
        """Proxy score for factual depth based on length and entity presence (numbers/quotes)."""
        text = f"{title} {body}".strip()
        if not text:
            return 0.1

        words = text.split()
        length = len(words)

        # Base length score
        if length > 500:
            base = 1.0
        elif length > 250:
            base = 0.8
        elif length > 100:
            base = 0.5
        else:
            base = 0.3

        # Bonus for numbers and quotes (proxy for data points/sources)
        has_quotes = '"' in text or "'" in text
        has_numbers = any(char.isdigit() for char in text)

        bonus = 0.0
        if has_quotes:
            bonus += 0.1
        if has_numbers:
            bonus += 0.1

        return min(1.0, base + bonus)

    def score_visualizability(self, title: str, body: str, has_image: bool) -> float:
        """Score how easily this translates to video scenes."""
        text = f"{title} {body}".lower()

        score = 0.3 # Base
        if has_image:
            score += 0.3

        # Keyword matches
        match_count = sum(1 for kw in self.VISUAL_KEYWORDS if kw in text)
        if match_count >= 2:
            score += 0.4
        elif match_count == 1:
            score += 0.2

        return min(1.0, score)

    def score_audience_interest(self, title: str, body: str) -> float:
        """Score based on Tech/AI keywords. Non-tech content gets heavily penalized."""
        text = f"{title} {body}".lower()

        match_count = sum(1 for kw in self.INTEREST_KEYWORDS if kw in text)
        if match_count == 0:
            return 0.05  # Non-tech topics get extremely low score
        elif match_count >= 2:
            return 1.0
        elif match_count == 1:
            return 0.8
        else:
            return 0.5

    def score_feasibility(self) -> float:
        """Score for production viability. Hardcoded to 1.0 for now, could be used for blacklist/complexity checks."""
        return 1.0

    def score_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Compute individual axis scores and total weighted score."""
        dt = datetime.datetime.fromisoformat(candidate["published_at_utc"].replace("Z", "+00:00"))
        norm_pub = candidate["normalized_publisher"]
        title = candidate["title"]
        body = candidate.get("body") or candidate.get("description") or ""
        has_image = bool(candidate.get("image_url"))

        freshness = self.score_freshness(dt)
        publisher = self.score_publisher(norm_pub)
        fact_density = self.score_fact_density(title, body)
        visual = self.score_visualizability(title, body, has_image)
        interest = self.score_audience_interest(title, body)
        feasibility = self.score_feasibility()

        # Weights
        w_fresh = 0.30
        w_pub = 0.20
        w_fact = 0.20
        w_vis = 0.15
        w_int = 0.10
        w_feas = 0.05

        total = (
            freshness * w_fresh +
            publisher * w_pub +
            fact_density * w_fact +
            visual * w_vis +
            interest * w_int +
            feasibility * w_feas
        )

        return {
            "total_score": round(total, 4),
            "axes": {
                "freshness": round(freshness, 4),
                "publisher_authority": round(publisher, 4),
                "fact_density": round(fact_density, 4),
                "visual_potential": round(visual, 4),
                "audience_interest": round(interest, 4),
                "feasibility": round(feasibility, 4),
            }
        }

    def rank_candidates(self, candidates: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
        """Score, sort, and return top N candidates. Stable tie-breaking via candidate_id."""
        scored = []
        for c in candidates:
            c_copy = c.copy()
            c_copy["scoring"] = self.score_candidate(c)
            scored.append(c_copy)

        # Sort by total score DESC, then candidate_id ASC for stable tie-breaking
        scored.sort(key=lambda x: (-x["scoring"]["total_score"], x["candidate_id"]))

        return scored[:limit]
