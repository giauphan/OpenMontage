# Proposed Skill: Honest Hook, Storytelling & Script Architecture

**Purpose:** retain users through useful narrative structure while delivering the EXACT promise. Not clickbait.  
**Input:** audience/claim ledger, format, actual test footage/evidence, approved cultural copy.  
**Output:** 3 hook candidates, selected hook rationale, full script with timecodes, visual proof plan, payoff map.

## Select a format based on material
- **News update:** what happened → who is impacted → evidence → what to watch next. Never report evergreen tutorials as news.
- **Comparison:** viewer decision → fair test criteria → real examples/results → conditions and trade-offs → whom to choose.
- **Tutorial:** problem → outcome shown → minimal steps → likely errors → takeaway.
- **Experiment:** question → method → result → surprising but honest limitation → implications.

## Short initial pilot (internal compatibility <=60 s)
- 0–3s: hook and visible evidence; no generic logo intro.
- 3–12s: why it matters to target viewer.
- 12–42s: one or two verified points, demo/screenshot/chart, scene match.
- 42–55s: honest outcome / useful takeaway.
- Final optional 3s: relevant prompt or related video, not spam CTA.
These time windows are **editorial heuristics**, not YouTube ranking rules.

## Long-form (6–10 min only if substance supports)
Hook with a demonstrated problem/outcome. Chapters based on test setup, meaningful comparison, result and limitations. Every chapter earns its duration; edit pauses/boilerplate. 16:9 YouTube longform is a distinct render + publisher path. Avoid forcing Shorts criteria or portrait output onto longform.

## Hook evaluation
Generate 3 alternatives: (1) practical outcome, (2) surprising evidence (not hype), (3) comparison/decision. Score on specificity, truthfulness, curiosity, early visual proof, and audience relevance. If no evidence supports a hook, revise hook or abort.

## Non-negotiable
- A hook claiming X must show/check X in the video. If the source doesn't establish X, don't claim it.
- Every script beat has `claim_ids`, `viewer_question`, `expected_visual`, `proof_shown` and `payoff_alignment`.
- No fabricated firsthand test, earnings, percentages, sponsorship, audience interviews, availability or product relationship.
- Use idiomatic en-US wording, voice rhythm, safe abbreviations.

## Output format
```yaml
format: shorts
hook_candidates:
  - id: H01
    text: "I tested this new AI feature on a real task—and caught a problem."
    condition: "Only after documented actual test"
selected_hook_id: H01
beats:
  - id: S01
    time_budget_s: 3
    viewer_question: "What's new?"
    claim_ids: [C001]
    proof_scene: V01
  - id: S02
    time_budget_s: 12
    viewer_question: "Why should I care?"
    claim_ids: [C002]
    proof_scene: V02
payoff_verified: false
```

Require `payoff_verified=true` from actual content and independent reviewer before delivery.
