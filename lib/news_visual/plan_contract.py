"""Contract validation and construction for artifacts/news_visual_plan.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "news" / "news_visual_plan.schema.json"


def load_plan_schema() -> Dict[str, Any]:
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Missing schema file: {SCHEMA_PATH}")
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_visual_plan(
    plan: Dict[str, Any],
    script_bytes: Optional[bytes] = None,
    evidence_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Validate news_visual_plan against schema, script, and evidence invariants."""
    errors: List[str] = []
    schema = load_plan_schema()
    validator = Draft202012Validator(schema)

    for err in sorted(validator.iter_errors(plan), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{loc}: {err.message}")

    if errors:
        return errors

    # Script binding validation
    if script_bytes is not None:
        expected_sha = hashlib.sha256(script_bytes).hexdigest()
        if plan.get("script_sha256") != expected_sha:
            errors.append(
                f"script_sha256 mismatch: plan has {plan.get('script_sha256')!r}, "
                f"expected {expected_sha!r}"
            )
        try:
            script_json = json.loads(script_bytes.decode("utf-8"))
            script_sections = {
                str(s.get("id")): s
                for s in script_json.get("sections", [])
                if isinstance(s, dict) and s.get("id")
            }
        except Exception as exc:
            errors.append(f"Cannot parse script bytes: {exc}")
            script_sections = {}

        # Validate section mapping and timestamps
        for i, beat in enumerate(plan.get("beats", [])):
            sec_id = str(beat.get("script_section_id"))
            if sec_id not in script_sections:
                errors.append(f"beats[{i}].script_section_id: {sec_id!r} not in script sections")
            start = float(beat.get("start_seconds", 0))
            end = float(beat.get("end_seconds", 0))
            if end <= start:
                errors.append(f"beats[{i}]: end_seconds ({end}) must be > start_seconds ({start})")

    # Evidence binding validation
    if evidence_data is not None:
        approved_claims = {
            str(c.get("id")): c
            for c in evidence_data.get("claims", [])
            if isinstance(c, dict) and c.get("id") and c.get("review_status") == "approved"
        }
        for i, beat in enumerate(plan.get("beats", [])):
            ev_class = beat.get("evidence_class")
            is_factual = ev_class in ("authentic_photo", "approved_source_visual", "approved_data_chart")
            for cid in beat.get("claim_ids", []):
                if is_factual and str(cid) not in approved_claims:
                    errors.append(
                        f"beats[{i}].claim_ids: claim {cid!r} is not approved in news_evidence.json"
                    )

    return errors
