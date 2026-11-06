"""Algorithmic semantic grounding and active claim fact-checking for Fixed Niche pipeline."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


POLARITY_PAIRS = (
    ("increas", "decreas"),
    ("increas", "reduc"),
    ("increas", "drop"),
    ("increas", "fall"),
    ("rise", "decreas"),
    ("rise", "reduc"),
    ("rise", "drop"),
    ("rise", "fall"),
    ("rose", "decreas"),
    ("rose", "reduc"),
    ("rose", "drop"),
    ("rose", "fall"),
    ("succeed", "fail"),
    ("success", "fail"),
    ("enabl", "disabl"),
    ("allow", "prevent"),
    ("allow", "block"),
    ("permit", "prohibit"),
    ("pass", "fail"),
    ("improv", "degrad"),
    ("accelerat", "decelerat"),
)

ALL_POLARITY_ROOTS = tuple(sorted({r for pair in POLARITY_PAIRS for r in pair}, key=len, reverse=True))

_ROOT_RE = re.compile(
    r"^(" + "|".join(map(re.escape, ALL_POLARITY_ROOTS)) + r")(?:e|es|ed|ing|s|ion|ions|ure|ures|ment|ful|fully|ped|ping|tion|tions|ement)?$"
)

IRREGULAR_ROOT_MAP = {
    "rose": "rise",
    "rising": "rise",
    "risen": "rise",
    "fell": "fall",
    "fallen": "fall",
}


def _polarity_root(word: str) -> Optional[str]:
    """Extract canonical polarity root if word matches allowed inflection suffixes or irregular forms."""
    canonical = IRREGULAR_ROOT_MAP.get(word, word)
    m = _ROOT_RE.match(canonical)
    if m:
        return m.group(1)
    m_raw = _ROOT_RE.match(word)
    return m_raw.group(1) if m_raw else None

NEGATION_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without|cannot|can[\'’]?t|don[\'’]?t|didn[\'’]?t|doesn[\'’]?t|wasn[\'’]?t|isn[\'’]?t|aren[\'’]?t|won[\'’]?t|wouldn[\'’]?t|couldn[\'’]?t|shouldn[\'’]?t|haven[\'’]?t|hasn[\'’]?t)\b",
    re.IGNORECASE,
)

STOP_WORDS = {
    "this", "that", "with", "from", "your", "what", "when", "where", "which", "into", "over",
    "across", "been", "have", "were", "model", "agent", "system", "using", "these", "those"
}


def _extract_polarity_associations(text: str) -> list[dict[str, Any]]:
    """Extract (metric, root, is_negated) associations per clause, isolating predicate-metric scopes."""
    clauses = re.split(r"[,;]|(?<=[.!?])\s+|(?:\b(?:while|but|and|whereas|although)\b)", text, flags=re.IGNORECASE)
    assocs: list[dict[str, Any]] = []
    for clause in clauses:
        words = re.findall(r"[a-zA-Z\'’]+", clause.lower())
        for i, w in enumerate(words):
            found_root = _polarity_root(w)
            if not found_root:
                continue

            # Check negation up to 3 words back in the same clause without crossing another predicate
            start_idx = max(0, i - 3)
            prior_words = words[start_idx:i]
            has_intervening_pred = any(bool(_polarity_root(pw)) for pw in prior_words)
            is_negated = False if has_intervening_pred else any(bool(NEGATION_RE.match(pw)) for pw in prior_words)

            context_metrics = [
                words[k]
                for k in range(len(words))
                if k != i
                and len(words[k]) >= 4
                and words[k] not in STOP_WORDS
                and not bool(_polarity_root(words[k]))
            ]

            if not context_metrics:
                assocs.append({"metric": "__all__", "root": found_root, "negated": is_negated})
            else:
                for m in context_metrics:
                    assocs.append({"metric": m, "root": found_root, "negated": is_negated})
    return assocs


def _has_contradiction(statement: str, sentence: str) -> bool:
    """Check if the sentence asserts direct opposite polarity or negated predicate for claimed metrics."""
    stmt_assocs = _extract_polarity_associations(statement)
    if not stmt_assocs:
        return False
    sent_assocs = _extract_polarity_associations(sentence)
    if not sent_assocs:
        return False

    compared: set[str] = set()
    contradicted: set[str] = set()
    for s in stmt_assocs:
        m = s["metric"]
        matching_sent = [sent for sent in sent_assocs if sent["metric"] == m or sent["metric"] == "__all__" or m == "__all__"]
        if not matching_sent:
            continue
        compared.add(m)
        # If the sentence explicitly supports this assertion (matching root & negation), no contradiction on this metric
        has_direct_support = any(sent["root"] == s["root"] and sent["negated"] == s["negated"] for sent in matching_sent)
        if has_direct_support:
            continue
        for sent in matching_sent:
            if s["root"] == sent["root"] and s["negated"] != sent["negated"]:
                contradicted.add(m)
                break
            if (
                ((s["root"], sent["root"]) in POLARITY_PAIRS or (sent["root"], s["root"]) in POLARITY_PAIRS)
                and (s["negated"] == sent["negated"])
            ):
                contradicted.add(m)
                break
    return bool(contradicted) and len(contradicted) >= min(2, len(compared))


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
    m = re.match(r'^([-+]?\d+(?:\.\d+)*)\s*(.*)$', q)
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
        r'\b\d+(?:\.\d+)*(?:\s*(?:%|(?:x|ms|sec|s|[kmb]?\s*tokens?|mb|gb|req/s|rps)\b)|[kmb]\b|\b(?![a-zA-Z]))',
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

    # 2. Extract claimed polarity metrics and content words
    stmt_assocs = _extract_polarity_associations(statement)
    stmt_metrics = {a["metric"] for a in stmt_assocs if a["metric"] != "__all__"}

    # Extract sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snap_str) if len(s.strip()) >= 15]
    if not sentences:
        sentences = [snap_str]

    polarity_verbs = {
        w.lower()
        for pair in POLARITY_PAIRS
        for r in pair
        for w in (r, r + "e", r + "es", r + "ed", r + "ing", r + "s", r + "ion", r + "tions", r + "ment", r + "ped", r + "ping")
    }
    words = set(re.findall(r"[a-zA-Z]{4,}", statement.lower())) - STOP_WORDS - polarity_verbs
    if not words:
        words = set(re.findall(r"[a-zA-Z]{4,}", statement.lower())) - {
            "this", "that", "with", "from", "your", "what", "when", "where", "which", "into", "over"
        }

    min_matches = 1 if len(words) <= 1 else 2

    # 3. Find candidate grounding sentence that actually supports the statement
    grounding_sentence = ""
    had_contradiction = False
    if candidate_excerpt and candidate_excerpt.strip() in snap_str:
        if _has_contradiction(statement, candidate_excerpt):
            had_contradiction = True
        else:
            norm_excerpt = _strip_thousands(candidate_excerpt.strip().lower())
            excerpt_matches = sum(1 for w in words if _matches_text(w, norm_excerpt))
            metrics_ok = not stmt_metrics or any(_matches_text(m, norm_excerpt) for m in stmt_metrics)
            quant_ok = all(
                bool(re.search(_quantity_regex(q), norm_excerpt, re.IGNORECASE))
                for q in stat_quantities
            )
            if excerpt_matches >= min_matches and metrics_ok and quant_ok:
                grounding_sentence = candidate_excerpt.strip()

    if not grounding_sentence:
        best_score = 0
        best_sent = ""
        for sent in sentences:
            if _has_contradiction(statement, sent):
                had_contradiction = True
                continue
            if stmt_metrics and not any(_matches_text(m, sent) for m in stmt_metrics):
                continue
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
        rejection_reason = (
            "Direct semantic polarity contradiction detected between statement and snapshot passage."
            if had_contradiction
            else "Failed to identify evidence passage supporting the statement in snapshot."
        )
        return {
            "verified_by": "FixedNicheFactCheckEngine",
            "verification_method": "ALGORITHMIC_SEMANTIC_GROUNDING",
            "verification_status": "UNVERIFIED",
            "grounding_sentence": "",
            "primary_domain": domain,
            "attestation": rejection_reason,
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
