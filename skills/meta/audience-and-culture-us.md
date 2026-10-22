# Proposed Skill: US Audience Intelligence & Cultural Context

**Type:** editorial research skill, NOT translation. **Invoke before script/scene direction.**  
**Inputs:** source candidates with timestamps and rights, intended format, audience profile `en-US`, previous analytics if available.  
**Outputs:** `audience_brief.json` + `topic_selection_report.md`; cite sources and assumptions.

## Goal
Know whose problem the video addresses and why an ordinary US YouTube viewer should care, without inventing US identity, spending power or cultural interests. English-speaking Canada is a secondary geographic segment; check actual differences rather than relying on stereotypes.

## Procedure
1. **Segment with intent**, not demographics as a shortcut: developer evaluating AI tools; freelancer wanting a faster workflow; small business testing practical automation; curious tech viewer interested in consequences. Choose exactly one primary persona per video.
2. Extract relevant outcome: time saved *if measured*, reliability, privacy, cost, capability, surprising trade-off, ease of setup; support every factual payoff with a source or own reproducible demo.
3. From dated sources, verify: Is product available in US? Canada? Free plan available? Is pricing USD or CAD, monthly/annual, tax included, promo-limited? Are the feature, model name and version current as of date? Avoid converting global price to USD without geographic price evidence.
4. Check audience/search language from credible current material and channel Analytics when available. Do not invent view demand or a competition index. If no data, record `HYPOTHESIS`.
5. Propose up to 3 distinct angles, each with a clear viewer job, original test/demo opportunity, and reason not to skip.
6. Decide `news / tutorial / comparison / explainer / skip`. News whose source cannot be verified is `skip` or `needs_review`.
7. Output an editorial reference sheet: US spelling, product tier terms, time zones, date representation, relevant standards/units, region availability and exclusions.

## Minimal data contract
```yaml
primary_persona: "US developer comparing AI coding tools"
viewer_job: "Choose a tool for code review with realistic constraints"
content_intent: "compare"
audience_hypotheses:
  - "This audience may value error-rate and cost demonstrations"
market: "US"
secondary_market: "English-speaking Canada"
region_restrictions: []
verified_us_specifics: []
assumptions_to_test: []
original_value: "run three reproducible tasks and show failures"
source_claim_ids: ["C001", "C002"]
recommendation: "PROCEED_WITH_EDITORIAL_REVIEW"
```

## Acceptance
- One specific viewer problem and one plausible payoff; no unverified US-only claim.
- Evidence of audience/context reasoning not merely changing script to American spelling.
- Each geographic availability or USD/CAD claim backed by a dated product/source page.
- Distinct angle and reproducible original contribution; no fake trend data.
- If no original value or timely credible evidence, `SKIP`.
