"""Multi-criteria transparent ranking for HookGuard candidates."""

from __future__ import annotations

from typing import Any, Optional


DEFAULT_WEIGHTS = {
    "relevance": 0.30,
    "coherence": 0.25,
    "viewer_promise": 0.25,
    "visual_relevance": 0.10,
    "audio_novelty": 0.10,
    "continuity_penalty": 0.20,
    "repetition_penalty": 0.20,
    "occlusion_risk": 0.15,
}


def score_candidate(
    candidate: dict[str, Any],
    weights: Optional[dict[str, float]] = None,
) -> float:
    """Compute transparent weighted score for a hook candidate."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    feats = candidate.get("rank_features", {})
    if not isinstance(feats, dict):
        feats = {}

    rel = float(feats.get("relevance", 0.5))
    coh = float(feats.get("coherence", 0.5))
    prom = float(feats.get("viewer_promise", 0.5))
    vis = float(feats.get("visual_relevance", 0.5))
    aud = float(feats.get("audio_novelty", 0.5))

    pen_cont = float(feats.get("continuity_penalty", 0.0))
    pen_rep = float(feats.get("repetition_penalty", 0.0))
    pen_occ = float(feats.get("occlusion_risk", 0.0))

    positive = (
        w["relevance"] * rel
        + w["coherence"] * coh
        + w["viewer_promise"] * prom
        + w["visual_relevance"] * vis
        + w["audio_novelty"] * aud
    )

    penalty = (
        w["continuity_penalty"] * pen_cont
        + w["repetition_penalty"] * pen_rep
        + w["occlusion_risk"] * pen_occ
    )

    score = round(max(0.0, min(1.0, positive - penalty)), 4)
    return score


def rank_candidates(
    candidates: list[dict[str, Any]],
    weights: Optional[dict[str, float]] = None,
) -> list[dict[str, Any]]:
    """Score and sort candidates in descending order of score."""
    ranked = []
    for cand in candidates:
        c_copy = dict(cand)
        c_copy["score"] = score_candidate(c_copy, weights=weights)
        ranked.append(c_copy)

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
