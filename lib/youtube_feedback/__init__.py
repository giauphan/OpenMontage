"""YouTube analytics and audience retention feedback package."""
from __future__ import annotations

from lib.youtube_feedback.retention_mapper import (
    HypothesisEntry,
    RetentionAnalysis,
    RetentionPoint,
    SceneTiming,
    generate_hypotheses_from_analysis,
    map_retention_curve,
)

__all__ = [
    "HypothesisEntry",
    "RetentionAnalysis",
    "RetentionPoint",
    "SceneTiming",
    "generate_hypotheses_from_analysis",
    "map_retention_curve",
]
