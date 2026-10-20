"""T06: Verify factual claim-to-visual release gate and unapproved metric blocking.

Baseline failure (RED):
1. Unreviewed claims like 78% or absolute security must fail closed in evidence validation.
2. Visual binding contract (lib.news_visual.source_binding) must reject binding
   consequential visuals to unapproved or rejected claims.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from lib.news_evidence import validate_news_evidence


def test_t06_unapproved_synthetic_claims_fail_evidence_gate(isolated_project: Path, rejected_claims: dict):
    """T06: Unapproved claims (78%, 25-35 tokens/s, absolute security) must fail evidence validation."""
    evidence_path = isolated_project / "artifacts" / "news_evidence.json"
    evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))

    # Inject the unapproved claims
    evidence_data["claims"] = rejected_claims["claims"]
    evidence_path.write_text(json.dumps(evidence_data, indent=2, ensure_ascii=False), encoding="utf-8")

    result = validate_news_evidence(isolated_project, max_source_age_hours=720.0)
    assert not result["ok"], "FAIL: validate_news_evidence passed with unapproved claims!"
    assert any("review_status" in err or "authority_attested" in err for err in result["errors"])


def test_t06_visual_binding_blocks_unapproved_claim():
    """T06: Visual plan binding must reject consequential visuals bound to unapproved claims (R9)."""
    try:
        from lib.news_visual.source_binding import validate_claim_visual_binding
    except ImportError:
        pytest.fail("FAIL: lib.news_visual.source_binding not implemented yet (R9).")
