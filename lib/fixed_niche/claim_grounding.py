"""Algorithmic semantic grounding and active claim fact-checking for Fixed Niche pipeline."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _stem_word(w: str) -> str:
    """Extract root stem for suffix-insensitive matching."""
    for suffix in ('ing', 'tions', 'tion', 'ence', 'ance', 'ized', 'izing', 'ize', 'ive', 'ed', 'es', 's'):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[:-len(suffix)]
    return w


def _matches_text(word: str, text: str) -> bool:
    """Check if word or its stem matches text as a word prefix."""
    stem = _stem_word(word)
    return bool(re.search(r'\b' + re.escape(stem), text.lower()))


def _strip_thousands(text: str) -> str:
    """Strip thousands separators from numbers (e.g. 10,000 -> 10000)."""
    return re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', text)


def _quantity_regex(q: str) -> str:
    """Build a regex pattern for a quantity with optional spacing between number and unit."""
    m = re.match(r'^([-+]?\d+(?:\.\d+)?)\s*(.*)$', q)
    if m:
        num_part = m.group(1)
        unit_part = m.group(2).strip()
        if unit_part:
            unit_pat = re.escape(unit_part) if unit_part.endswith('%') else re.escape(unit_part) + r'\b'
            return r'(?<!\d)(?<!\d\.)' + re.escape(num_part) + r'\s*' + unit_pat
        return r'(?<!\d)(?<!\d\.)' + re.escape(num_part) + r'\b(?!\.\d)'
    return r'\b' + re.escape(q) + r'\b'


def verify_independent_claim(
    statement: str,
    snapshot_text: str,
    publisher: str = "",
    canonical_url: str = "",
    candidate_excerpt: Optional[str] = None,
    candidate_fact_check: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Perform active algorithmic claim grounding against source snapshot.

    Verifies that the statement is semantically grounded in the snapshot,
    that any quantitative figures and units are present in the snapshot,
    and identifies the exact grounding sentence.
    """
    domain = canonical_url.split("//")[-1].split("/")[0] if canonical_url else ""
    snap_str = (snapshot_text or "").strip()
    if not snap_str:
        return {
            "verified_by": "FixedNicheFactCheckEngine",
            "verification_method": "ALGORITHMIC_SEMANTIC_GROUNDING",
            "verification_status": "UNVERIFIED",
            "grounding_sentence": "",
            "primary_domain": domain,
            "attestation": "No snapshot content available for grounding.",
        }

    norm_statement = _strip_thousands(statement)
    norm_snap = _strip_thousands(snap_str)

    # 1. Number and unit verification: Any quantitative figures in statement must exist with their units in snapshot
    stat_quantities = re.findall(
        r'\b\d+(?:\.\d+)?(?:\s*(?:%|(?:x|ms|sec|s|[kmb]?\s*tokens?|mb|gb|req/s|rps)\b)|[kmb]\b|\b(?![a-zA-Z]))',
        norm_statement,
        re.IGNORECASE,
    )
    stat_quantities = [q.strip() for q in stat_quantities if q.strip() and any(c.isdigit() for c in q)]
    for q in stat_quantities:
        pat = _quantity_regex(q)
        if not re.search(pat, norm_snap, re.IGNORECASE):
            return {
                "verified_by": "FixedNicheFactCheckEngine",
                "verification_method": "ALGORITHMIC_SEMANTIC_GROUNDING",
                "verification_status": "UNVERIFIED",
                "grounding_sentence": "",
                "primary_domain": domain,
                "attestation": f"Ungrounded quantitative figure '{q}' not found in source snapshot.",
            }

    # 2. Extract sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snap_str) if len(s.strip()) >= 15]
    if not sentences:
        sentences = [snap_str]

    words = set(re.findall(r"[a-zA-Z]{4,}", statement.lower())) - {
        "this", "that", "with", "from", "your", "what", "when", "where", "which", "into", "over"
    }

    min_matches = 1 if len(words) <= 1 else 2

    # 3. Find candidate grounding sentence that actually supports the statement
    grounding_sentence = ""
    if candidate_excerpt and candidate_excerpt.strip() in snap_str:
        norm_excerpt = _strip_thousands(candidate_excerpt.strip().lower())
        excerpt_matches = sum(1 for w in words if _matches_text(w, norm_excerpt))
        quant_ok = all(
            bool(re.search(_quantity_regex(q), norm_excerpt, re.IGNORECASE))
            for q in stat_quantities
        )
        if excerpt_matches >= min_matches and quant_ok:
            grounding_sentence = candidate_excerpt.strip()

    if not grounding_sentence:
        best_score = 0
        best_sent = ""
        for sent in sentences:
            norm_sent = _strip_thousands(sent)
            matches = sum(1 for w in words if _matches_text(w, sent))
            if stat_quantities and not all(
                re.search(_quantity_regex(q), norm_sent, re.IGNORECASE)
                for q in stat_quantities
            ):
                continue
            if matches >= min_matches and matches > best_score:
                best_score = matches
                best_sent = sent

        if best_score >= min_matches:
            grounding_sentence = best_sent

    if not grounding_sentence or grounding_sentence not in snap_str:
        return {
            "verified_by": "FixedNicheFactCheckEngine",
            "verification_method": "ALGORITHMIC_SEMANTIC_GROUNDING",
            "verification_status": "UNVERIFIED",
            "grounding_sentence": "",
            "primary_domain": domain,
            "attestation": "Failed to identify evidence passage supporting the statement in snapshot.",
        }

    verified_entity = "FixedNicheFactCheckEngine"
    if candidate_fact_check and candidate_fact_check.get("verified_by"):
        verified_entity = f"FixedNicheFactCheckEngine ({candidate_fact_check['verified_by']})"

    return {
        "verified_by": verified_entity,
        "verification_method": "ALGORITHMIC_SEMANTIC_GROUNDING",
        "verification_status": "INDEPENDENT_FACT_CHECK_VERIFIED",
        "grounding_sentence": grounding_sentence,
        "primary_domain": domain,
        "attestation": f"Verbatim sentence grounding verified in source snapshot from {publisher} ({domain}).",
    }
