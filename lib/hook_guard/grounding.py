"""Factuality, grounding, entity, numerical, date, and negation verification for HookGuard."""

from __future__ import annotations

import re
from typing import Any, Optional


# Negation words to track
NEGATION_WORDS = frozenset({
    "not", "never", "no", "none", "neither", "nor", "nowhere",
    "hardly", "scarcely", "barely", "cannot", "can't", "won't",
    "isn't", "aren't", "wasn't", "weren't", "haven't", "hasn't",
    "hadn't", "doesn't", "don't", "didn't", "shouldn't", "wouldn't",
    "impossible", "unable",
})

# Words that denote exaggeration/absolute claims
ABSOLUTE_WORDS = frozenset({
    "always", "guaranteed", "proven", "cure", "miracle", "secret",
    "impossible", "undeniable", "100%", "everyone", "nobody",
})


def _extract_dates(text: str) -> list[str]:
    """Extract year and date patterns."""
    pattern = r"\b(19\d\d|20\d\d)(?:-\d{1,2}-\d{1,2})?\b"
    return re.findall(pattern, text)


def _extract_numbers(text: str) -> list[str]:
    """Extract numbers, percentages, currencies, and multipliers (excluding 4-digit years)."""
    pattern = r"(\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?[xkm]?\b|\$\d+(?:\.\d+)?)"
    matches = re.findall(pattern, text.lower())
    years = set(_extract_dates(text))
    filtered = []
    for m in matches:
        m_str = m.strip()
        if m_str in years:
            continue
        filtered.append(m_str)
    return filtered


def _extract_negations(text: str) -> set[str]:
    """Extract negation words present in text."""
    words = re.findall(r"\b\w+(?:'\w+)?\b", text.lower())
    return set(words).intersection(NEGATION_WORDS)


def _normalize_text_for_comparison(text: str) -> str:
    """Lowercase and strip punctuation."""
    return re.sub(r"[^\w\s]", " ", text.lower())


def verify_hook_grounding(
    candidate: dict[str, Any],
    source_context: Optional[dict[str, Any]] = None,
) -> tuple[bool, Optional[str], dict[str, Any]]:
    """Verify that a hook candidate is strictly grounded in evidence.
    
    Checks:
      1. Presence of evidence spans or citations.
      2. Numerical and percentage fidelity.
      3. Date and temporal fidelity.
      4. Negation preservation (no inverted facts).
      5. News verification (independent provenance, URL, publication date).
      
    Returns:
      (is_valid, reason_code_if_invalid, diagnostics_dict)
    """
    text = str(candidate.get("text", "")).strip()
    if not text:
        return False, "REJECTED_EMPTY_TEXT", {"error": "Candidate text is empty"}

    evidence_list = candidate.get("evidence", [])
    if not evidence_list:
        return False, "REJECTED_UNSUPPORTED_CLAIM", {
            "error": "No evidence attached to hook candidate",
            "candidate_text": text,
        }

    # Aggregate all evidence text and claims
    evidence_texts: list[str] = []
    for ev in evidence_list:
        if not isinstance(ev, dict):
            continue
        if ev.get("claim"):
            evidence_texts.append(str(ev["claim"]))
        if ev.get("citation"):
            evidence_texts.append(str(ev["citation"]))

    # Also include context transcript/script if passed
    if source_context:
        if source_context.get("transcript"):
            evidence_texts.append(str(source_context["transcript"]))
        if source_context.get("script"):
            evidence_texts.append(str(source_context["script"]))
        if source_context.get("brief"):
            evidence_texts.append(str(source_context["brief"]))

    combined_evidence = " ".join(evidence_texts)
    norm_evidence = _normalize_text_for_comparison(combined_evidence)
    evidence_words = set(norm_evidence.split())

    # Check 1: News First requirement
    intent = candidate.get("intent")
    if intent == "news_first":
        has_news_provenance = False
        for ev in evidence_list:
            if ev.get("kind") == "external_source" and ev.get("source_url") and ev.get("publication_date"):
                has_news_provenance = True
                break
            if ev.get("source_url") and (ev.get("publication_date") or ev.get("event_date")):
                has_news_provenance = True
                break
        if not has_news_provenance:
            return False, "REJECTED_UNVERIFIED_NEWS", {
                "error": "news_first hook requires external evidence with source_url and publication/event date",
                "candidate_text": text,
            }

    # Check 2: Date claims
    hook_dates = _extract_dates(text)
    if hook_dates:
        evidence_dates = set(_extract_dates(combined_evidence))
        unmatched_dates = [d for d in hook_dates if d not in evidence_dates]
        if unmatched_dates:
            return False, "REJECTED_DATE_MISMATCH", {
                "error": f"Candidate dates not supported by evidence: {unmatched_dates}",
                "candidate_dates": hook_dates,
                "evidence_dates": list(evidence_dates),
            }

    # Check 3: Numerical claims
    hook_numbers = _extract_numbers(text)
    if hook_numbers:
        evidence_numbers = set(_extract_numbers(combined_evidence))
        unmatched_numbers = []
        for num in hook_numbers:
            # Check direct match or plain digits match (e.g. 73% vs 73)
            plain_digits = re.sub(r"[^\d.]", "", num)
            found = False
            for ev_num in evidence_numbers:
                ev_digits = re.sub(r"[^\d.]", "", ev_num)
                if num == ev_num or (plain_digits and plain_digits == ev_digits):
                    found = True
                    break
            if not found:
                unmatched_numbers.append(num)

        if unmatched_numbers:
            return False, "REJECTED_NUMERICAL_MISMATCH", {
                "error": f"Candidate numbers not supported by evidence: {unmatched_numbers}",
                "candidate_numbers": hook_numbers,
                "evidence_numbers": list(evidence_numbers),
            }

    # Check 4: Negation inversion
    hook_negations = _extract_negations(text)
    evidence_negations = _extract_negations(combined_evidence)
    # If the hook has strong negation words (e.g. "never", "nobody") but evidence has none:
    extreme_negations = hook_negations.intersection({"never", "nobody", "nowhere", "impossible"})
    if extreme_negations and not evidence_negations.intersection(extreme_negations):
        # Unless evidence explicitly supports the exact phrase:
        phrase_found = any(word in norm_evidence for word in extreme_negations)
        if not phrase_found:
            return False, "REJECTED_NEGATION_MISMATCH", {
                "error": f"Candidate introduces unsupported absolute negation: {extreme_negations}",
            }

    # Check 5: Word/character overlap / entity check
    cjk_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    if cjk_chars:
        overlap_chars = [c for c in cjk_chars if c in combined_evidence]
        char_ratio = len(overlap_chars) / len(cjk_chars)
        if char_ratio < 0.20:
            return False, "REJECTED_UNSUPPORTED_CLAIM", {
                "error": f"Low evidence CJK character overlap ({char_ratio:.2f})",
                "candidate_text": text,
            }
    else:
        hook_words = [w for w in _normalize_text_for_comparison(text).split() if len(w) > 3]
        if hook_words and evidence_words:
            overlap = [w for w in hook_words if w in evidence_words]
            overlap_ratio = len(overlap) / len(hook_words)
            has_visual_evidence = any(
                isinstance(ev, dict) and ev.get("kind") in ("source_range", "visual_event")
                for ev in evidence_list
            )
            # Hook must have some lexical/conceptual grounding in the evidence
            if overlap_ratio < 0.25 and intent not in ("topic_question", "problem_first") and not has_visual_evidence:
                return False, "REJECTED_UNSUPPORTED_CLAIM", {
                    "error": f"Low evidence word overlap ({overlap_ratio:.2f})",
                    "overlap_words": overlap,
                    "hook_words": hook_words,
                }

    return True, None, {"status": "GROUNDED", "evidence_count": len(evidence_list)}
