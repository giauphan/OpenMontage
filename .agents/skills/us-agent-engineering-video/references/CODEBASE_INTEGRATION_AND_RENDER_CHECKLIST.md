# How to produce ONE new coding-agent explainer through CURRENT OpenMontage

**Applies to** OpenMontage HEAD `c30371e` and future code after verification. This is a developer implementation guide, NOT a claim these new commands already exist. Follow the main master plan for migration/test ordering.

## Absolute channel constraints

- ONE human-chosen fixed niche: practical AI agent engineering for US developers.
- Daily AI agent may choose only subtopic, evidence angle, episode format, hook, proof visualization and voice settings permitted by operator; may not choose different niche.
- Distinguish `news` (publish date matters) and `evergreen` (technical accuracy matters). A published source can be older than a day without invalidating an evergreen explanation.
- If no admissible topic with source/proof, exit `NO_ELIGIBLE_TOPIC` without modifying publishing queue.

## Step 0: One project, one question

Example **topic**, not a claimed vendor defect: "What information can be lost when an AI coding-agent session restarts?" Viewer: developer using agents across a real repository. Specific outcome: how to verify durable project instructions versus ephemeral conversation context. The video needs one conceptual diagram and, if actual demo is available, one real captured before/after state. If no demo, never say “I tested.”

## Step 1: Candidate and policy

Inputs: `candidate_id`, title, original source URL, timestamp if news, source kind, content kind. Normalize via existing NewsNow adapter where valid; gate with new `lib/fixed_niche/gate.py`, then score. `fixed_niche_scope.json` snapshot ties policy SHA, viewer problem, allowed topic family and candidate ID. Reject all broad "AI news roundup" candidates before LLM or project initialization. Only authorized operator can change the niche policy.

## Step 2: Fact ledger

Use existing `lib/news_source_capture.py` / `lib/news_claim_review.py`. Capture primary docs as hash-bound snapshots with exact sections. Proposed atomic claims: active context depends on context supplied to session; external durable files can persist; whether a named tool automatically reads those files is product/version-specific. Do **not** turn these generic statements into false claims about all AI agents. Record `DOCUMENTED`, `OBSERVED`, or `INFERRED` classification.

## Step 3: Real demo decision

A "how-to" or failure demonstration may require sandbox:

1. Create isolated temp repo fixture without any credentials or private user code.
2. Pin agent CLI, model, settings, OS/container image versions and input files.
3. Capture exact commands, expected outputs and test assertions first.
4. Run actual process under time/network/CPU limits; save exit code, stdout/stderr, hash, timestamps and redacted screenshot.
5. Do **not** fabricate a failure if the test passes; alter script claim, label mechanism as hypothetical, or reject the episode.
6. Attach `demo_protocol.json`, `demo_results.json` and hash-bound proof IDs. A failed reproduction is still a truthful result but must not be described as proven failure.

## Step 4: Script and hook

Use THREE hooks: problem-first, evidence-first and decision-first. Only select one after direct match with source or genuine demo. Script ~65–75 actual seconds when duration schema migrated; speech rate determined by synthesized final audio, not a guessed word count. One topic, one payoff, natural US technical vocabulary, actual version qualifiers. Output current `artifacts/script_en_US.json` with section IDs/times. Do not alter legacy VI output.

## Step 5: Source-bound visual storyboard

Canonical output remains `artifacts/news_visual_plan.json` plus `video_proof_map.json`. For each beat attach: `script_section_id`, `claim_ids`, `evidence_class`, `asset_ids`, `visual_kind`, `background_preset`, `motion_preset`, `start/end`. Distinguish `authentic_proof`, `conceptual_diagram`, `illustration`, `typographic_focus`.

For context-loss episode: draw labeled boxes `Conversation Context` -> `Session Boundary`; independent `Repo Instructions` box -> `Explicit Reload` -> `New Session`; demonstrate lost vs persisted paths with a red dotted arrow and green solid arrow. If evidence supports only "may" rather than "will", reflect that in on-screen wording. Use SVG paths/arrows/text as explanatory geometry; large topic title on gradient **fails visual relevance**. Show document citations in description/source panel as appropriate, not random logos.

## Step 6: Create real assets, never proof placeholders

Create `assets/visuals/context-lifecycle.svg`, `assets/visuals/new-session-verify.svg` with technical layout; capture real terminal screenshot only if sandbox executed and screenshot license/PII safe. Validate `lib/news_visual/asset_resolver.py` paths and hashes and `lib/news_visual/plan_contract.py` claim IDs. Stage copies into BOTH `hyperframes/assets/visuals` and `hyperframes_reels/assets/visuals` using `scripts/prepare_news_visuals.py`. If resolver would generate current placeholder SVG for a proof beat, reject before TTS (do not silently accept its file-valid fallback). Preserve illustration label for non-real UI.

## Step 7: Use native production TTS

Invoke existing `tools.audio.narration_cli` from actual project root (after source/script validated). Preferred provider configured by operator; `omniroute` cloud where eligible or `kokoro` / `pocket18` local when benchmarked. Audio integrity via `ffprobe`, full narration same voice, atomic output. Keep exact `assets/narration.mp3`. After final voice, run `scripts/generate_news_captions.py` for actual audio bytes, produce caption assets/timestamps; do not use mock WEBVTT in published video. Update scene timings to measured voice. On voice rewrite, invalidate prior captions and approval.

## Step 8: Render (dynamic project path)

Use `hyperframes render hyperframes --output renders/final_long_en_US_16x9.mp4` and `hyperframes render hyperframes_reels --output renders/final_short_en_US_9x16.mp4` with cwd set to **current new `project_dir`** and with shared media CPU governor. These are example invocations relying on existing HyperFrames CLI, not a new wrapper that exists today. Do not use fixture-specific `render_short()` in `scripts/render_verified_deliverables.py` without first refactoring it to accept project dir and proving no old fixtures are touched. If the 16:9 companion is just the same 75-second content, call it "landscape cut", not "6–10 minute longform". In a later independent longform flow, write a separate deep script and demonstrate enough substantive steps.

## Step 9: Sample real decoded MP4, not HTML only

Use ffprobe to assert resolution/frame rate/audio duration. Render frame contact sheet from 0s/1s/3s, every beat midpoint, transitions, and last 2s. Independently inspect with visual QA: explanation visible, diagram text readable at mobile size, no mismatched claim, no made-up terminal, no blank freeze, no caption overlap, no generic fallback. Confirm actual captions match final words and do not cover source label/important arrow.

## Step 10: Independent QA and release state

Run existing `scripts/validate_news_visuals.py` strict and render validator, source snapshots/claim ledger, plus new niche gate recheck and video proof map validation. Independent reviewer (not same model self-approving) checks exact source and real video frames, verifies title/hook payoff, media rights and final signature hash. Private canary only after operator authorization. If the signed inputs or MP4 change after approval, release gate must fail and request new review.

## Decision tables and anti-patterns

| Symptom | Diagnosis | Required action |
|---|---|---|
| Topic outside channel niche | Scope conflict | Block; DO NOT ask AI to choose a new niche |
| No video-worthy topic today | No evidence, no viewer problem | `NO_ELIGIBLE_TOPIC`; no quota padding |
| Director wrote "I tested" but none run | Untruthful original-value claim | Block or rewrite as documented mechanism |
| SVG has only title text on dark rect | Generic default visual | Block proof beat; generate actual technical schematic |
| `run_us_ai_director_pipeline.py` says Stage 5 passed without MP3 synthesis | Validator misinterpreted as generator | Use actual narration CLI and assert file hash |
| `render_verified_deliverables.render_short()` touched sample project | Hardcoded fixture renderer invoked | Stop; refactor to project-dir or use HyperFrames directly |
| 59.9s MP4 fails min60s | Duration contract mismatch | Fix script/audio timing and tested en-US profile, no fake freeze tail |
| Changed narration but same captions | Stale ASR | Invalidate audio cache dependency and rerun caption transcription |
| 2 CPU-heavy jobs overlap | Shared resource control missing in one subprocess | Wrap entire heavy process with same lock; benchmark |
| Evergreen item rejected as stale "news" | Wrong evidence policy | Use evergreen evidence gate, never relax true news freshness |

## Required handoff evidence per completed video

`topic_brief.json`, `fixed_niche_scope.json`, verified source bundle / ledger, `script_en_US.json`, visual proof map, actual stage assets, final narration MP3/hash, captions, two compositions, real MP4+ffprobe JSON, decoded frame samples, final QA/signature, and human-readable failed checks. Missing any required proof -> NOT VIDEO_READY.
