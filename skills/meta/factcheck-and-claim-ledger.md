# Proposed Skill: Skeptical News Research & Claim Ledger

**Invoke:** after discovery and before copywriting, voice or asset generation. Reinvoke after *any* meaningful rewrite.  
**Input:** URLs, captured excerpts/metadata, publication timestamp, topic candidates, planned title/hook and claims.  
**Output:** versioned claim ledger and source bundle with hashes. Do not author final conclusions where evidence is missing.

## Verification checklist
1. Establish **what happened** vs **when it happened**. Distinguish source publication, event/release date, last-edited date, and retrieval timestamp; all internally timezone-aware ISO timestamps.
2. Read original primary sources: product release notes, official model cards, docs, changelogs, author papers, regulator/SEC filings or first-party demo. Secondary analysis adds context but isn't proof of a product's own terms.
3. Decompose narration/title/hook/scene charts into atomic claims: entity, action, time, place, number, qualifier, uncertainty. No unsupported comparative superlatives like "fastest", "free", "replaces everyone", "first ever".
4. For pricing, bench tests and limitations: capture plan/version/date, methodological conditions, geography, currencies and taxes. Say "In our three tests..." instead of presenting small samples as general scientific conclusion.
5. Resolve contradictions by source authority and recency; preserve meaningful disagreements. If not resolvable, qualify explicitly or remove the claim.
6. Cross-map approved claim IDs to script phrases and scenes, and retain **original evidence byte hashes**. On edit/hot refresh/hash mismatch, invalidate downstream approval and recalculate.
7. Assess manipulated content and forged screenshots. Reproduced product UI screenshots must come from actual tests with access rights, or diagrams must be plainly labeled `illustration`.
8. The native editorial writer must preserve all qualifiers from claim ledger. Re-run claim consistency after localization and title revision.

## Output contract (illustrative)
```json
{
  "claim_id": "C001",
  "statement": "Feature X is available to users on the named plan in the US",
  "confidence": "verified",
  "scope": {"market":"US","plan":"named plan","as_of":"YYYY-MM-DD"},
  "source": {"canonical_url":"https://example.invalid/primary-source","publisher":"official vendor","published_at":"ISO8601 timezone aware","retrieved_at":"ISO8601 timezone aware","source_sha256":"<sha256>"},
  "evidence_excerpt_locator":"section/paragraph, do not reprint long copyrighted text",
  "limitations":["availability subject to rollout"],
  "script_spans":["S03"],
  "visual_scene_ids":["V03"],
  "verdict":"APPROVED_WITH_QUALIFIER"
}
```

## Hard blocks
- Source date unavailable but presented as breaking news; conflicting sources without stated uncertainty; fabricated or inferred version numbers, release times, benchmark or costs.
- Claim materially changes under English rewrite, or screenshot/chart contradicts its source.
- Missing provenance or source hash, suspicious privately hosted source, unknown media rights.

## Important
An AI agent cannot reliably decide truth based on a fabricated consensus of AI agents. Require independent source evidence and reviewer-readable ledger. A passing factcheck does **not** guarantee YouTube performance.
