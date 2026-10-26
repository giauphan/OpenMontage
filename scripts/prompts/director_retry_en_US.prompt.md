Mode: Bounded Artifact Repair (en-US / US Market)

Repair incomplete or invalid outputs for {{PROJECT_DIR}} only. Read the current files and {{PROJECT_DIR}}/artifacts/research_brief.json first. Do not invoke pipeline wrappers, renderers, publishers, schedulers, social APIs, SSH, subagents, or background work. Do not accept stale files as success. Do not author static captions/subtitles; the pipeline installs validated ASR caption clips. Reserve the bottom 16% of each portrait scene as a clear caption-safe rail and keep all other text, footers, tickers, and plates above it.

Repair only these artifacts:
- {{PROJECT_DIR}}/artifacts/script_en_US.json
- {{PROJECT_DIR}}/hyperframes/index.html
- {{PROJECT_DIR}}/hyperframes_reels/index.html
- {{PROJECT_DIR}}/artifacts/news_visual_plan.json (when visual planning is active)

Target Audience & Cultural Localization:
- Audience: United States technology professionals, developers, and tech enthusiasts.
- Editorial Standard: Self-contained US English tech documentary standard (do NOT open or search external `skills/`, `scripts/`, or other `projects/` files).
- Voice & Tone: Confident, fast-paced, insightful, authoritative American tech documentary narration.
- Idiomatic Precision: Use 100% natural, idiomatic American English. NEVER use Vietnamese words, diacritics, or translation calques. Every section MUST be a complete, grammatically sound English sentence (never truncate or cut off text mid-sentence or mid-word).
- Duration: Rich spoken-word narration, measured synthesized narration in 65–75s ([65, 75]s) with no 180s content exception. Word count is advisory (~155–175 spoken words). Use at least 6 distinct source-backed visual beats and keep any one scene visible for at most 12s. Never pad the final scene or trim narration mid-sentence.

Preserve valid content. Fix missing schema keys, malformed JSON, missing composition roots (must be a closed direct child of `<body>` with `id="stage" data-composition-id="main"`), canvas dimensions (`hyperframes/index.html` MUST be 1920x1080 landscape; `hyperframes_reels/index.html` MUST be 1080x1920 portrait), missing scene/timeline registration, broken relative assets (use `assets/visuals/...`, never `../assets/`), invalid Reels duration, low-contrast text (must be bright #fff/#f8fafc on dark cards), scene transition gaps (no empty frames), repetitive layouts, and forbidden visible branding. Visual styling is mandatory: never use a solid plain background (#stage must use rich dark radial gradients), and wrap scene content in glassmorphic cards with glowing borders (#38bdf8), large metric callouts, and category badges. Ensure every scene's GSAP entrance and opacity transition matches script_en_US.json section start_seconds so visual transitions are strictly aligned with narration audio. Keep ticker/status bars from overlapping footer metadata or text. Keep output self-contained and compatible with the existing HyperFrames renderer. Do not change providers, models, runtimes, or source material.

News evidence and factual grounding: Base all script content strictly on the technology news in {{PROJECT_DIR}}/artifacts/research_brief.json and any supplied frozen source excerpts. Map factual assertions strictly to verified claims in `research_brief.json`. Never invent citations, excerpts, URLs, benchmark numbers, quotes, or product specifications. Never create or edit news_evidence.json, self-attest human editorial review, or fill reviewer/reviewed_at fields; news evidence binding and verification are automated pipeline steps that execute downstream after script generation.

Seek-safe authoring requirements (apply to both composition HTML files): create one `gsap.timeline({ paused: true })`; put every animation, including scene opacity/visibility changes, on that timeline using `tl.to/from/fromTo/set`; register the fully constructed timeline synchronously as `window.__timelines['main']`. Never use standalone `gsap.to/from/fromTo/set`, `repeat: -1`, timers, asynchronous timeline construction, or unregistered timelines. Keep motion finite and purposeful; do not add decorative motion solely to evade the frozen-canvas check. Do not read or set `tl.duration()` until all child animations have been added. Preserve exact section start times with explicit timeline positions and keep scenes visible across transitions. If a validation error is supplied with this retry, fix each listed error in the relevant HTML and do not merely report it.

Finish synchronously and verify:
test -s "{{PROJECT_DIR}}/artifacts/script_en_US.json" && test -s "{{PROJECT_DIR}}/hyperframes/index.html" && test -s "{{PROJECT_DIR}}/hyperframes_reels/index.html"

Return exactly one final status line:
- DIRECTOR_REPAIR_OK project={{PROJECT_DIR}}
- DIRECTOR_REPAIR_FAILED project={{PROJECT_DIR}} reason=<concise reason>
