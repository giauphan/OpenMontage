"""Fixed niche topic scorer and semantic deduplication.

Scores in-scope topics according to the owner's pilot rubric:
- Specific developer problem / payoff: 30%
- Verifiable primary-source evidence: 25%
- Scene / diagram / demo feasibility: 20%
- Distinctiveness vs recent channel episodes: 15%
- Timeliness (only for timely news; evergreen receives neutral score): 10%
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.fixed_niche.gate import ScopeVerdict


class FixedNicheTopicScorer:
    """Scores candidate topics that have ALREADY passed the deterministic scope gate."""

    EDITORIAL_THRESHOLD = 0.75

    STOP_WORDS = {
        "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is",
        "are", "was", "were", "why", "how", "what", "when", "where", "can", "do",
        "does", "with", "between", "across", "about", "your", "this", "that", "from"
    }

    def __init__(self, reference_time: Optional[datetime] = None):
        self.reference_time = reference_time or datetime.now(timezone.utc)

    @staticmethod
    def stem(word: str) -> str:
        """Lightweight stemmer stripping common English suffixes for deduplication."""
        w = word.lower().strip()
        for suffix in ("ing", "tion", "tions", "ence", "ance", "ment", "ness", "ity", "ies", "es", "s", "ed"):
            if w.endswith(suffix) and len(w) > len(suffix) + 2:
                return w[:-len(suffix)]
        return w

    def extract_keywords(self, text: str) -> Set[str]:
        """Extract stemmed significant keywords for semantic deduplication."""
        words = re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", text.lower())
        return {self.stem(w) for w in words if w not in self.STOP_WORDS}

    def check_duplicate(
        self,
        candidate: Dict[str, Any],
        history: List[Dict[str, Any]],
        threshold: float = 0.40,
    ) -> Tuple[bool, str]:
        """Check whether candidate duplicates a previously covered thesis or engineering claim."""
        cand_text = f"{candidate.get('viewer_question', '')} {candidate.get('title', '')} {candidate.get('body', '')}"
        cand_kw = self.extract_keywords(cand_text)
        cand_family = candidate.get("topic_family")

        for past in history:
            past_family = past.get("topic_family")
            if cand_family and past_family and cand_family != past_family:
                continue

            past_kw = set()
            for kw in past.get("thesis_keywords", []):
                past_kw.add(self.stem(kw))

            if not past_kw:
                past_text = f"{past.get('viewer_question', '')} {past.get('title', '')} {past.get('body', '')}"
                past_kw = self.extract_keywords(past_text)

            if not cand_kw or not past_kw:
                continue

            intersection = cand_kw & past_kw
            union = cand_kw | past_kw
            jaccard = len(intersection) / len(union) if union else 0.0

            # Check question token overlap specifically
            q1_words = self.extract_keywords(candidate.get("viewer_question", ""))
            q2_words = self.extract_keywords(past.get("viewer_question", ""))
            q_jaccard = (
                len(q1_words & q2_words) / len(q1_words | q2_words)
                if (q1_words and q2_words)
                else 0.0
            )

            if jaccard >= threshold or q_jaccard >= 0.45:
                overlap_terms = ", ".join(sorted(list(intersection))[:5])
                return (
                    True,
                    f"Duplicate thesis detected (overlap score {max(jaccard, q_jaccard):.2f}, shared terms: {overlap_terms})",
                )

        return False, ""

    def score_problem_payoff(self, candidate: Dict[str, Any]) -> float:
        """Score concrete viewer problem and developer payoff (30%)."""
        viewer_job = candidate.get("viewer_job") or candidate.get("viewer_question")
        title = candidate.get("title", "")
        body = candidate.get("body", "")

        score = 0.70
        if viewer_job and len(str(viewer_job)) > 10:
            score += 0.20
        # Positive indicators of concrete developer problems
        if re.search(r"\b(fail|regression|mismatch|error|loss|break|deadlock|leakage|tampering)\b", f"{title} {body}", re.I):
            score += 0.10
        return min(1.0, score)

    def score_primary_evidence(self, candidate: Dict[str, Any]) -> float:
        """Score verifiable primary source evidence (25%)."""
        url = candidate.get("canonical_url") or candidate.get("url") or ""
        pub = candidate.get("publisher") or ""

        score = 0.50
        # Official docs, RFCs, specs, verified GitHub issues
        if re.search(r"(docs\.|specification|rfc|ietf|modelcontextprotocol|github\.com|arxiv\.org)", url, re.I):
            score += 0.35
        elif re.search(r"(official|spec|changelog|research)", pub, re.I):
            score += 0.30

        if candidate.get("source_snapshot") or candidate.get("claim_ids"):
            score += 0.15
        return min(1.0, score)

    def score_visual_feasibility(self, candidate: Dict[str, Any]) -> float:
        """Score feasibility of producing explanatory diagrams or verifiable logs (20%)."""
        text = f"{candidate.get('title', '')} {candidate.get('body', '')}"
        # Highly diagrammable concepts
        if re.search(r"\b(schema|flow|boundary|container|checkpoint|architecture|tree|ast|timeline|diff)\b", text, re.I):
            return 0.95
        return 0.80

    def score_distinctiveness(self, candidate: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None) -> float:
        """Score distinctiveness vs channel history (15%)."""
        if not history:
            return 1.0
        is_dup, _ = self.check_duplicate(candidate, history)
        return 0.10 if is_dup else 0.90

    def score_timeliness(self, candidate: Dict[str, Any], verdict: ScopeVerdict) -> float:
        """Score timeliness (10%). Breaking news prioritized by recency; evergreen receives baseline score."""
        is_evergreen = verdict.content_kind == "evergreen_explainer" or candidate.get("content_kind") == "evergreen_explainer"
        if is_evergreen:
            return 0.70  # Baseline for evergreen architectural explainers

        pub_at = candidate.get("published_at") or candidate.get("published_at_utc")
        if not pub_at:
            return 0.70

        try:
            if isinstance(pub_at, str):
                dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
            elif isinstance(pub_at, datetime):
                dt = pub_at
            else:
                return 0.70

            age_hours = (self.reference_time - dt).total_seconds() / 3600.0
            if age_hours <= 12.0:
                return 1.0
            elif age_hours <= 24.0:
                return 0.95
            elif age_hours <= 72.0:
                return 0.90
            elif age_hours <= 168.0:  # Within 7 days
                return 0.85
            else:
                return 0.50
        except Exception:
            return 0.70

    def score_candidate(
        self,
        candidate: Dict[str, Any],
        verdict: ScopeVerdict,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compute weighted score for a candidate that passed the scope gate."""
        prob_score = self.score_problem_payoff(candidate)
        evid_score = self.score_primary_evidence(candidate)
        vis_score = self.score_visual_feasibility(candidate)
        dist_score = self.score_distinctiveness(candidate, history)
        fresh_score = self.score_timeliness(candidate, verdict)

        # Weighted calculation
        total = (
            prob_score * 0.30
            + evid_score * 0.25
            + vis_score * 0.20
            + dist_score * 0.15
            + fresh_score * 0.10
        )

        return {
            "candidate_id": candidate.get("id") or candidate.get("candidate_id"),
            "problem_payoff_score": round(prob_score, 3),
            "evidence_score": round(evid_score, 3),
            "visual_feasibility_score": round(vis_score, 3),
            "distinctiveness_score": round(dist_score, 3),
            "freshness_score": round(fresh_score, 3),
            "total_score": round(total, 3),
            "passes_editorial_threshold": total >= self.EDITORIAL_THRESHOLD,
        }

    def rank_candidates(
        self,
        candidates_with_verdicts: List[Tuple[Dict[str, Any], ScopeVerdict]],
        history: Optional[List[Dict[str, Any]]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Rank eligible candidates by total weighted score."""
        scored = []
        for cand, verdict in candidates_with_verdicts:
            if not verdict.is_eligible:
                continue
            scores = self.score_candidate(cand, verdict, history)
            scored.append({**cand, **scores, "topic_family": verdict.topic_family})

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        return scored[:limit]
