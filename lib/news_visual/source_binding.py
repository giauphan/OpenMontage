"""Source and claim binding validation for visual elements."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def validate_claim_visual_binding(
    visual_spec: Dict[str, Any],
    evidence_data: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Validate that visual elements claiming factual status are backed by approved claims."""
    errors: List[str] = []
    evidence_class = visual_spec.get("evidence_class", "none")
    claim_ids = visual_spec.get("claim_ids", [])
    label = visual_spec.get("label", "unnamed_visual")

    # Approved claims map
    approved_claims = {}
    all_claims = {}
    for c in evidence_data.get("claims", []):
        if isinstance(c, dict) and c.get("id"):
            cid = str(c["id"])
            all_claims[cid] = c
            if c.get("review_status") == "approved":
                approved_claims[cid] = c

    # Factual evidence requirements
    is_factual = evidence_class in ("authentic_photo", "approved_source_visual", "approved_data_chart")

    if is_factual:
        if not claim_ids:
            errors.append(
                f"{label}: factual visual ({evidence_class}) must link to at least one approved claim_id."
            )
        for cid in claim_ids:
            cid_str = str(cid)
            if cid_str not in all_claims:
                errors.append(f"{label}: claim_id {cid!r} does not exist in news_evidence.json.")
            elif cid_str not in approved_claims:
                claim = all_claims[cid_str]
                status = claim.get("review_status", "unreviewed")
                reason = claim.get("rejection_reason", "missing approval")
                errors.append(
                    f"{label}: claim {cid!r} is rejected or unapproved (status={status!r}, reason={reason!r}). "
                    "Cannot display unverified claim as factual evidence (R9)."
                )

    # Numerical claim safeguard: prevent deceptive unapproved metric cards
    text_content = str(visual_spec.get("text") or visual_spec.get("heading") or "")
    unapproved_metric_match = re.search(r"\b(\d+%\s*|\d+[\s-]*\d+\s*tokens?/s|bảo mật tuyệt đối)\b", text_content, re.IGNORECASE)
    if unapproved_metric_match and not is_factual:
        errors.append(
            f"{label}: visual contains numerical/absolute claim '{unapproved_metric_match.group(0)}' "
            "without approved factual evidence class."
        )

    return len(errors) == 0, errors
