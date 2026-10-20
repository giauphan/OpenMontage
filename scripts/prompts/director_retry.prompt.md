Mode: Bounded Artifact Repair

Repair incomplete or invalid outputs for {{PROJECT_DIR}} only. Read the current files and {{PROJECT_DIR}}/artifacts/research_brief.json first. Do not invoke pipeline wrappers, renderers, publishers, schedulers, social APIs, SSH, subagents, or background work. Do not accept stale files as success. Do not author static captions/subtitles; the pipeline installs validated ASR caption clips. Reserve the bottom 16% of each portrait scene as a clear caption-safe rail and keep all other text, footers, tickers, and plates above it.

Repair only these artifacts:
- {{PROJECT_DIR}}/artifacts/script_vi.json
- {{PROJECT_DIR}}/hyperframes/index.html
- {{PROJECT_DIR}}/hyperframes_reels/index.html
- {{PROJECT_DIR}}/artifacts/news_visual_plan.json (when visual planning is active)

Preserve valid content. Fix missing schema keys, malformed JSON, missing portrait roots, missing scene/timeline registration, broken relative assets, invalid Reels duration, Vietnamese text defects (NEVER truncate or cut off text mid-sentence), short duration (script must have 180-240 spoken words across 5 scenes: intro, context, details, impact, conclusion totaling 60-75s, minimum 60s), low-contrast text (must be bright #fff/#f8fafc on dark cards), scene transition gaps (no empty frames), repetitive layouts, and forbidden visible branding. Visual styling is mandatory: never use a solid plain background (#stage must use rich dark radial gradients), and wrap scene content in glassmorphic cards with glowing borders (#38bdf8), large metric callouts, and category badges. Ensure every scene's GSAP entrance and opacity transition matches script_vi.json section start_seconds so visual transitions are strictly aligned with narration audio. Keep ticker/status bars from overlapping footer metadata or text. Keep output self-contained and compatible with the existing HyperFrames renderer. Do not change providers, models, runtimes, or source material.

News evidence and factual grounding: Base all script content strictly on the technology news in {{PROJECT_DIR}}/artifacts/research_brief.json and any supplied frozen source excerpts. Never create or edit news_evidence.json, self-attest human editorial review, fill reviewer/reviewed_at fields, or invent citations, excerpts, URLs, source dates, or verification; news evidence binding and verification are automated pipeline steps that execute downstream after script generation.

Seek-safe authoring requirements (apply to both composition HTML files): create one `gsap.timeline({ paused: true })`; put every animation, including scene opacity/visibility changes, on that timeline using `tl.to/from/fromTo/set`; register the fully constructed timeline synchronously as `window.__timelines['main']`. Never use standalone `gsap.to/from/fromTo/set`, `repeat: -1`, timers, asynchronous timeline construction, or unregistered timelines. Keep motion finite and purposeful; do not add decorative motion solely to evade the frozen-canvas check. Do not read or set `tl.duration()` until all child animations have been added. Preserve exact section start times with explicit timeline positions and keep scenes visible across transitions. If a validation error is supplied with this retry, fix each listed error in the relevant HTML and do not merely report it.


Finish synchronously and verify:
test -s "{{PROJECT_DIR}}/artifacts/script_vi.json" && test -s "{{PROJECT_DIR}}/hyperframes/index.html" && test -s "{{PROJECT_DIR}}/hyperframes_reels/index.html"

Return exactly one final status line:
- DIRECTOR_REPAIR_OK project={{PROJECT_DIR}}
- DIRECTOR_REPAIR_FAILED project={{PROJECT_DIR}} reason=<concise reason>
