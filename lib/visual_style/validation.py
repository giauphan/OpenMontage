"""Contract and security validation for diagram animation artifacts.

Enforces:
1. JSON Schema Draft 2020-12 compliance
2. Graph referential integrity (nodes, edges, targets)
3. Timing and event bounds
4. Provenance and strict SHA256 checks
5. Security allowlists and XSS prevention

Target module size: < 450 lines.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "visual_style" / "diagram_animation.v1.schema.json"

# Security regexes for untrusted active content or malicious payloads
FORBIDDEN_SVG_PATTERNS = [
    re.compile(r"<\s*script\b", re.I),
    re.compile(r"<\s*foreignObject\b", re.I),
    re.compile(r"<\s*iframe\b", re.I),
    re.compile(r"<\s*object\b", re.I),
    re.compile(r"<\s*embed\b", re.I),
    re.compile(r"\bon[a-z]+\s*=", re.I),  # event handlers like onload=, onerror=
    re.compile(r"javascript\s*:", re.I),
    re.compile(r"data\s*:\s*text/html", re.I),
]


class DiagramContractError(ValueError):
    """Raised when a diagram plan violates contract, schema, or referential integrity."""
    pass


class DiagramSecurityError(ValueError):
    """Raised when malicious active content or disallowed attributes are detected."""
    pass


def load_diagram_schema() -> Dict[str, Any]:
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Missing diagram schema at {SCHEMA_PATH}")
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_security_string(text: str, context: str = "field") -> None:
    """Validate that a string does not contain script injection, XSS vectors, or forbidden tags."""
    if not text:
        return
    for pattern in FORBIDDEN_SVG_PATTERNS:
        if pattern.search(text):
            raise DiagramSecurityError(
                f"Security violation in {context}: disallowed active content pattern '{pattern.pattern}' detected"
            )


def validate_diagram_plan_data(
    data: Dict[str, Any],
    *,
    strict_hashes: bool = False,
) -> List[str]:
    """Validate diagram animation plan against schema and semantic/security invariants.

    Returns list of error messages (empty if valid).
    """
    errors: List[str] = []

    # 1. JSON Schema validation
    schema = load_diagram_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"schema.{loc}: {err.message}")

    if errors:
        return errors

    # 2. Extract and check uniqueness of IDs
    nodes = data.get("graph", {}).get("nodes", [])
    edges = data.get("graph", {}).get("edges", [])
    beats = data.get("beats", [])
    events = data.get("events", [])

    node_ids: List[str] = [str(n["id"]) for n in nodes]
    edge_ids: List[str] = [str(e["id"]) for e in edges]
    beat_ids: List[str] = [str(b["id"]) for b in beats]
    event_ids: List[str] = [str(e["id"]) for e in events]

    if len(node_ids) != len(set(node_ids)):
        errors.append("graph.nodes contains duplicate IDs")
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("graph.edges contains duplicate IDs")
    if len(beat_ids) != len(set(beat_ids)):
        errors.append("beats contains duplicate IDs")
    if len(event_ids) != len(set(event_ids)):
        errors.append("events contains duplicate IDs")

    overlap = set(node_ids) & set(edge_ids)
    if overlap:
        errors.append(f"Collision between node IDs and edge IDs: {overlap}")

    node_set = set(node_ids)
    edge_set = set(edge_ids)
    all_targets = node_set | edge_set

    # 3. Check edge endpoints
    for i, edge in enumerate(edges):
        src = str(edge.get("source"))
        tgt = str(edge.get("target"))
        if src not in node_set:
            errors.append(f"edges[{i}].source '{src}' not found in nodes")
        if tgt not in node_set:
            errors.append(f"edges[{i}].target '{tgt}' not found in nodes")

    # 4. Check beats contiguity and hold limits
    prev_end = 0.0
    beat_map: Dict[str, Dict[str, Any]] = {}
    total_dur = float(data.get("duration_seconds", 72.0))

    for i, b in enumerate(beats):
        bid = str(b["id"])
        beat_map[bid] = b
        st = float(b["start_seconds"])
        en = float(b["end_seconds"])
        if abs(st - prev_end) > 0.001:
            errors.append(f"beats[{i}].start_seconds ({st}) does not match previous end ({prev_end})")
        hold = round(en - st, 4)
        if hold <= 0:
            errors.append(f"beats[{i}] hold ({hold}s) must be positive")
        elif hold > 12.0001:
            errors.append(f"beats[{i}] hold ({hold}s) exceeds maximum 12.0s ceiling")
        prev_end = en

    if abs(prev_end - total_dur) > 0.05:
        errors.append(f"Sum of beat durations ({prev_end}s) does not match duration_seconds ({total_dur}s)")

    # 5. Check events validity
    for i, ev in enumerate(events):
        tgt = str(ev.get("target"))
        bid = str(ev.get("beat_id"))
        at_s = float(ev.get("at_seconds", 0.0))
        dur_s = float(ev.get("duration_seconds", 0.0))

        if tgt not in all_targets:
            errors.append(f"events[{i}].target '{tgt}' not found in nodes or edges")

        if bid not in beat_map:
            errors.append(f"events[{i}].beat_id '{bid}' not found in beats")
        else:
            beat = beat_map[bid]
            b_st = float(beat["start_seconds"])
            b_en = float(beat["end_seconds"])
            if not (b_st - 0.001 <= at_s <= b_en + 0.001):
                errors.append(f"events[{i}].at_seconds ({at_s}) is outside beat '{bid}' range [{b_st}, {b_en}]")

            ev_claims = set(ev.get("claim_ids", []))
            beat_claims = set(beat.get("claim_ids", []))
            if not ev_claims.issubset(beat_claims):
                errors.append(f"events[{i}].claim_ids ({ev_claims}) must be subset of beat claims ({beat_claims})")

        if at_s + dur_s > total_dur + 0.05:
            errors.append(f"events[{i}] ends at {at_s+dur_s}s, exceeding total duration {total_dur}s")

    # 6. Strict SHA256 checks
    if strict_hashes:
        for key in ["script_sha256", "source_visual_plan_sha256", "source_claim_ledger_sha256", "policy_sha256"]:
            val = str(data.get(key, ""))
            if val == "0" * 64 or not re.match(r"^[0-9a-f]{64}$", val):
                errors.append(f"{key} has placeholder/invalid hash in strict production mode: {val}")

    # 7. Security scanning of labels and strings
    for i, n in enumerate(nodes):
        try:
            validate_security_string(n.get("label", ""), f"nodes[{i}].label")
        except DiagramSecurityError as sec_err:
            errors.append(str(sec_err))

    for i, e in enumerate(edges):
        if e.get("label"):
            try:
                validate_security_string(e.get("label", ""), f"edges[{i}].label")
            except DiagramSecurityError as sec_err:
                errors.append(str(sec_err))

    return errors
