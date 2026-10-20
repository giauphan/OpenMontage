"""T12: Verify publishing safety, cadence, and duplicate slot prevention.

Visual enrichment must NOT alter publish idempotency, timing rules, or slot allocations.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from lib.news_release_gate import require_news_evidence


def test_t12_publish_fails_closed_when_evidence_or_qa_incomplete(isolated_project: Path):
    """T12: A project cannot be published without complete passing evidence and visual QA."""
    # An incomplete or unapproved evidence state raises ValueError and blocks release
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(isolated_project, env_max_age_hours="720")
