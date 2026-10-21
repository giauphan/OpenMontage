# Proposed Skill: US-Native Cultural Localization (NOT Translation)

**Role:** Native-minded editorial writer plus independent cultural QA reviewer.  
**Invoke:** after claim evidence and audience brief, before script approval, again after TTS sample and on title/thumbnail review.  
**Input:** verified claim ledger, persona, evidence, raw source briefing (may be Vietnamese), intended US viewer task, planned format.  
**Output:** fresh en-US script, cultural audit, pronunciation glossary, change log against claims.

## Core principle
**Language is how an audience makes sense of a situation, not just words.** Reconstruct the narrative from verified facts and the US viewer's problem; don't translate sentence-by-sentence from Vietnamese. Never fake first-person US experience or generalize a nation as a single culture. Maintain factual fidelity exactly, including qualifiers and currency.

## Localize 8 layers
1. **Angle/importance:** why this particular person in the US cares (privacy, workflow, buying decision, trade-offs), not generic "the latest tech in the world".
2. **Pragmatics:** concise, direct, friendly, non-patronizing; avoid forced TikTok slang, fake excitement or exaggerated certainty.
3. **Cultural references:** a specific, commonly understood task/context works better than a Vietnamese-only reference. Do not invent a cultural fact; prefer universal workplace/student/software situations.
4. **Lexicon and voice:** natural American English collocations; choose US spellings unless quoting names/brands; avoid awkward passive constructions and literal idioms.
5. **Numbers/units/currency:** USD only for verified US prices, CAD for Canada-specific prices, US date ambiguity resolved, units appropriate to subject; never silently alter statistics.
6. **Locale/availability:** "available in the US" only when verified; Canada is not interchangeable with US, and English speakers in Canada aren't all the same.
7. **Humor/sensitivity:** avoid stereotypes, slang invented from translations, insensitive comparisons and unsupported anxiety/fear claims.
8. **Delivery and visual language:** titles, voice, captions, screen-recording labels and thumbnail use the same target terms, with consistent names/abbreviations.

## Example rewrite (hypothetical concept — NOT a sourced fact)
Vietnamese-style briefing: `AI mới mạnh hơn, tiết kiệm thời gian, ai cũng nên dùng.`

**Unacceptable literal English:** "The new AI is more powerful and saves time, everyone should use it." Why fail: vague, unsupported universal recommendation and benefit.

**US-native script proposal, conditional on footage:** "I put this tool through three everyday tasks: drafting an email, fixing a spreadsheet formula, and reviewing a pull request. One feature helped. Two still needed manual checking. Here's what I found." Why better: clear viewer job, original controlled test, honest limitation. ONLY SAY IT if three tasks were actually tested; otherwise plan the experiment first.

Another example:
- Weak: "A shocking model from China destroys ChatGPT." (sensational, politically loaded and unsupported comparison)
- Preferred: "I tested the new model on two coding tasks. Here's where it handled errors better—and where it didn't." (if tests exist and details shown)

## Native review rubric (0–5 each; threshold is a proposed editorial test, not platform law)
- Original angle and audience value
- Natural conversational US English
- Cultural/region relevance and accuracy
- Claim fidelity and qualifiers
- Clarity/flow/length for format
- Title/hook/payoff alignment
- Voice/TTS readability and name accuracy
- Onscreen wording consistency

**Required:** ≥32/40 for automatic recommendation to human; no item below 3; all hard factual blockers clear. Human review remains required for initial canaries. Never fabricate an actual native reviewer: report whether reviewed by a human, language model, or unverified.

## Explicit reject cases
- VN references that don't fit the audience but were translated unchanged; Vietnamese hashtags; English with incorrect tool/product name; false US-specific availability; unexplained CAD-as-USD; exaggerated fear/hype; fake expert voice; scripts that hide important limitations.

## Reviewer output
```json
{"language":"en-US","editor_type":"model_precheck_or_human","score":null,"hard_blockers":[],"claim_diffs":[],"phrasing_notes":[],"region_notes":[],"pronunciation_glossary":{},"decision":"REVISE_OR_READY_FOR_HUMAN"}
```
