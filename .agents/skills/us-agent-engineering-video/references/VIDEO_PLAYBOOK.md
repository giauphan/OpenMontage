# Detailed practical video playbook — fixed niche ONLY

## Output objective

For the US developer viewer, produce a distinctive, understandable 9:16 animated technical explainer using **source-verified concepts or actual safe experiment logs**, not generic AI b-roll. The video should answer exactly ONE agent-engineering question in 65–75 seconds after coherent migration of en-US profile duration limits and validators. The program only selects the specific topic within the owner's one locked niche.

### Worked EXAMPLE episode (not a claim about a real product)

- **Episode question:** "Why can an AI coding agent forget your project's requirements between sessions?"
- **Content class:** evergreen mechanism explainer, **NOT a claim that any named vendor loses memory**.
- **Audience:** US developer with an existing codebase.
- **Proposed payoff:** understand what information disappears across a session boundary and how to create a verified project-context handoff.
- **Permissible evidence:** official docs for the chosen coding tool's documented context behavior and local toy-session demonstration if available. Without primary docs or demo, use *generic conceptual explanation* and avoid naming vendors or claiming measured loss.
- **Video style:** dark high-contrast technical animated diagrams, real code excerpts when licensed, small caption-safe subtitles, no random robotic humanoid imagery.
- **Possible title (conditional):** "Why Your Coding Agent Loses Project Context" only when script is accurately framed as a possible behavior, not a universal incident.

## Step 1 — proof bundle BEFORE script

Create a topic packet with one-sentence engineering question and these files:

- `artifacts/fixed_niche_scope.json`: locked niche ID, config SHA256, topic family, PASS, input candidate ID and date.
- `artifacts/research_brief.json` using the repository's existing schema. Back all meaningful findings with source URLs and source snapshots.
- `artifacts/claim_ledger.json`: each claim has ID, literal statement, scope/versions, evidence locator, source hash, classification DOCUMENTED/OBSERVED/INFERRED, decision.
- Optional `artifacts/demo_protocol.json` and `artifacts/demo_results.json`: only when an experiment was actually run. Keep commands/versions/exit status/stdout-stderr samples, redacted secrets, timestamps.
- `artifacts/agent_visual_storyboard.json`: per scene claim, time budget, visual proof, element labels, source provenance and fallbacks.

Block downstream if no primary evidence, unsupported title, unbounded vendor generalization or a fake "I tested" claim. If a real screenshot cannot be sourced legally, generate a **labeled conceptual SVG diagram** instead.

## Step 2 — generate three candidate hooks with truth check

1. Problem-first hook: "Your agent can lose the project goal when the session changes." Use only if qualified by evidence/context and illustrated.
2. Mechanism hook: "A new chat doesn't necessarily load your project rules. Here's the missing link." Requires docs supporting the mechanism; avoid universal claim.
3. Decision hook: "Stop repeating project instructions: save the requirements your next session needs." This is an editorial suggestion, not a benchmark claim.

Score each internally for specificity, evidence strength, viewer payoff, first-frame visual and no false urgency. Select only a proven hook, no cold brand intro, no suspense without payoff.

## Step 3 — write the script at measured pace

- Pilot **65–75 seconds** after updating the existing en-US profile maximum (currently 60s) and testing the already-existing 60s minimum render gate. Choose a draft at a natural verified voice pace; ALWAYS ffprobe actual generated audio. Never make a 59.9-second clip pass by appending frozen/silent padding.
- One narrator, US-idiomatic vocabulary. Explain jargon on first use if essential: "context" as instructions and project details the model sees; "checkpoint" as a saved summary/state artifact.
- One primary question. No filler "In this exciting video". No unsupported superlatives or claim that a company deliberately hides limitations.
- Prepare both `narration` text and separate on-screen text; do not blindly display whole spoken paragraphs on screen.
- Each line references `claim_ids` and a visual that can actually be produced.

## Step 4 — concrete timecoded storyboard (first 60 seconds of a 65–75s episode; use 60–75s for careful caveat and payoff)

| Time | Narration function (not final verbatim script) | Visuals | QA must verify |
|---|---|---|---|
| 0–3 s | Show the exact user problem as a question | Screen split: `SESSION A` with checked goal vs `SESSION B` blank goal; striking **illustrative** mismatch highlight | Frame 0 nonblank; problem visible; no false screenshot framing |
| 3–9 s | Why it matters to a coder | Minimal editor schematic: user's requirement + task + repo icon; a new session begins | Labels readable on phone; no fake real app identity |
| 9–18 s | Explain boundary between active context and stored files | Diagram with live context box; arrow to ending session; separate durable project notes box | Arrows represent described mechanism only; label concept as diagram |
| 18–29 s | Identify a failure path and what is missing | Flow `request → available context → tool call → patch`; a missing requirements input flagged | Evidence-backed causal link, no fabricated terminal logs |
| 29–41 s | Explain a safe remedy within documented constraints | Save brief: requirements, decisions, tests, current status; connect to next session via explicit read step | Do not claim that all tools will load this automatically |
| 41–52 s | Show how to verify behavior | Conceptual check: new-session input list → ask to restate requirements → run applicable test; optional REAL captured log overlay if available | Never show fictitious pass status as actual measurement |
| 52–65 s | Caveat and payoff | Summarize: persistence must be explicit and verified; show two-column comparison of "assumed" vs "verified" | One clear conclusion, coherent ending, correct claim qualifiers |

Each scene must have `scene_id`, `start_s`, `end_s`, `spoken_beats`, `claim_ids`, `source_asset_ids`, `visual_intent`, `background_style`, `typography`, `motion_spec`, `caption_safe_bounds`, `evidence_status`, `fallback_asset_kind` and `qa_checks`.

## Step 5 — asset selection: exact priority order

For every scene, prefer (a) actual test artifact source with permission, (b) original technical diagram calculated from a verified claim, (c) authorized official screenshot tied to a documented feature, (d) licensed authentic contextual image when the claim is about a physical product, (e) clearly labeled explanatory schematic. **Never choose a generic gradient or stock data-center image as the main proof for a code-memory problem**. Decorative backgrounds are secondary and context-matched.

Build original SVG/HTML animations for sessions, tool calls, permission boundaries, file snapshots, test state timelines, cost flow; use consistent visual grammar but change the information design every episode. Avoid logos as proof. Check SVG is visible in final render and all asset references exist in both full and reels directories. Use the repo's existing visual plan, asset resolver and claim-bound visual checks rather than introducing a competing renderer.

## Step 6 — motion and composition direction

- For vertical 1080×1920, reserve caption-safe rail per existing release templates, account for mobile UI obscuring areas; choose readable font size by frame preview rather than one magic pixel number.
- Use purposeful arrows, highlight, shape morph, separation/merge of state boxes. No excessive wobble or constant zoom that destabilizes captions.
- Every major beat introduces or resolves one visual state; at least one meaningful visual change every several seconds, without arbitrary decorative movement.
- All major claims and diagrams have IDs so reviewers can point to the exact failing scene.
- Actual timebases come from audio and composition timeline; scene entrances must be synchronized with words, not merely planned timestamps.

## Step 7 — TTS and audio QC

- A single pin-stable American voice per video. Use configured providers without assuming any free cloud quota; commercial rights verified by operator/provider account.
- Preflight a short excerpt containing "API", "MCP", "Claude Code", and "context window" only if those terms appear in script. Listen or use pronunciation QA to ensure clarity.
- Synthesize final text, cache by normalized script+provider/model+voice+settings; write output atomically. `ffprobe` duration/codec/channels; test silence/clipping, levels, missing tails and truncated sentences.
- If fallback changes voice, redo whole narration; then rerun ASR captions from final audio and invalidate affected visual timing and approval.
- Generate word timings from final audio; never reuse stale caption timestamps after changing narration. On 2 vCPU use one local TTS or ASR at a time; never race with render.

## Step 8 — render and sample actual frames

- Existing compose/render contract: `hyperframes` + `hyperframes_reels`, dynamic project directory (not hardcoded sample render helper), final artifact `renders/final_short_en_US_9x16.mp4`; preserve production hash metadata and release checks.
- Render once at a time. Probe with `ffprobe`; sample 0/1/3/10/18/29/41/52/end seconds, plus every scene transition. Inspect visual semantics, clipping, text overlap, caption rail, media attribution and first-frame clarity.
- Validate soundtrack versus subtitles, and on-screen code/commands against source evidence. If a stock/photo asset is unrelated, replace with a claim-linked original diagram, **not a different random stock image**.
- Reject final if any key scene shows empty gradient, fake proof, unreadable text, missing fonts, abrupt audio cutoff or mismatched code.

## Step 9 — independent release gate

QA reviewer must compare title/hook, each critical claim, proof locator, visual output, actual audio, subtitles, render, metadata, URLs, rights and approval hash. A score alone cannot override a missing evidence hard block. If any validated file changes after signing, invalidate and repeat review. Do not publish automatically; use private canary only upon explicit approval.

## Step 10 — variations without changing niche

The final 65–75-second segment must contain a source-appropriate caveat and a complete spoken conclusion. The next episode can cover an *entirely different failure mechanism* (MCP tool schema mismatch), an architecture decision (single vs multi-agent), or an evidence-based engineering comparison. These are content topics within the **same locked Practical AI Agent Engineering niche**. No daily market scan is allowed to rebrand the channel or change viewer persona.

## Acceptance before returning VIDEO_READY_FOR_PRIVATE_REVIEW

- Policy ID/hash match frozen channel.
- One clearly in-scope engineering question.
- At least one verified primary source; numbers backed individually.
- If first-hand experiment claimed, saved real logs and environment provenance exist.
- Every important beat maps to matching visual proof/illustration and quote qualifiers.
- Audio final and caption timestamps match; one consistent voice.
- Target render decodes, aspect/duration correct; no blank/glitchy key frames.
- Independent QA and source/media rights pass; publication disabled unless owner approves.
