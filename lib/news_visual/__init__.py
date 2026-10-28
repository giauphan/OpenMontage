"""OpenMontage Context-Aware News Visual Pipeline Package.

Provides contracts, schemas, asset resolvers, layout builders, and QA validators
for grounded visual news videos.
"""

from __future__ import annotations

from lib.news_visual.thumbnail_orchestrator import (
    ImageGeneratorPort,
    ThumbnailOrchestrator,
    ThumbnailResult,
)
from lib.news_visual.thumbnail_planner import ThumbnailPlan, ThumbnailPlanner

__version__ = "1.0.0"

__all__ = [
    "ThumbnailPlan",
    "ThumbnailPlanner",
    "ThumbnailOrchestrator",
    "ThumbnailResult",
    "ImageGeneratorPort",
]
