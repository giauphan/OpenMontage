Mode: Initial Generation

Generate or repair all three director outputs for {{PROJECT_DIR}}.

1. script_vi.json
Must be a flat JSON file at {{PROJECT_DIR}}/artifacts/script_vi.json (do not embed inside checkpoint).
Schema keys: version (1.0), title, total_duration_seconds, sections (array of: id, text, start_seconds, end_seconds).
Content: 100% correct Vietnamese spelling, exact grammatical tone marks, correct technical terminology. Rich spoken-word narration, 180-240 spoken words total (60-75s expected spoken duration, minimum 60s). No dead air. Use a strong 3-second hook. CRITICAL DURATION GOAL: Videos must reach at least 60 seconds (1 minute or more). Never write fewer than 180 Vietnamese words. CRITICAL: NEVER truncate or cut off text mid-sentence or mid-word (e.g. ending abruptly in "...chỉ k"). Every section MUST be a complete, grammatically sound, fully articulated Vietnamese sentence.

News evidence and factual grounding: Base all script content strictly on the technology news in {{PROJECT_DIR}}/artifacts/research_brief.json and any supplied frozen source excerpts. Never create or edit news_evidence.json, claim that editorial review occurred, fill reviewer/reviewed_at fields, or invent citations, excerpts, URLs, source dates, or verification; news evidence binding and verification are automated pipeline steps that execute downstream after script generation.

2. hyperframes/index.html & hyperframes_reels/index.html
hyperframes/index.html: The complete story with no sections/narration removed. Portrait 1080x1920 CSS layout. Duration matches the full text (60-75s).
hyperframes_reels/index.html: Identical structure but shortened to <=60s for Instagram Reels.
Content & Quality for both:
- NO visible "Montage" or "OpenMontage" branding anywhere.
- Grounding: Base the narration and on-screen text 100% on the factual technology news in {{PROJECT_DIR}}/artifacts/research_brief.json. Do not invent unrelated numbers or generic filler.
- Visual scene diversity, visual intent & styling (MANDATORY):
  * Content-first visual intent: Every narrative beat must declare a clear visual_intent and evidence_class (e.g. authentic_photo, svg_diagram, contextual_icon, or typographic_focus).
  * For major technical concepts, hardware, or architecture, author an actual SVG diagram or bind an approved staged source image from `assets/visuals/` — do NOT rely on text-only cards. A text-only card requires explicit editorial rationale.
  * Never fabricate arbitrary unverified asset paths. In visual mode, consume staged local files from `assets/visuals/` or inline deterministic SVG layers.
  * Scene-specific art direction: Distinct scenes must have distinct, context-relevant visual treatment (e.g. technical diagram layout, flow arrows, or authentic device imagery). Do not wrap every scene in an identical glassmorphic text box on a uniform gradient.
  * Progressive voice-synchronized diagrams: NEVER display all diagram blocks simultaneously at t=0 when explaining workflows, architectures, or multi-step agent pipelines (e.g. hook -> agent -> tools -> output). Structure diagrams into semantic groups (`#flow-step-1`, `#flow-arrow-1`, `#flow-step-2`...) and reveal blocks sequentially matching the spoken voice narration via GSAP tweens on `window.__timelines['main']` or embedded keyframes.
  * FORBIDDEN RAW EMOJIS (CRITICAL): NEVER use raw Unicode emojis (e.g. 🔍, 🤖, 🚀, 💡, ⚡) anywhere in HTML text, diagram boxes, or cards. The headless Linux Chromium renderer lacks color emoji fonts and renders them as missing glyph tofu boxes []. Always use inline vector SVG icons (`<svg viewBox="0 0 24 24">...</svg>`) or clean text labels.
  * NO TRAILING PERIODS ON METRICS OR LABELS: NEVER append a period to metric values (e.g. write `SOTA` never `SOTA.`; `Higher ↑` never `Higher ↑.`; `38.3%` never `38.3%.`), directional flow arrows (`↓` never `↓.`), acronyms, dates, or badges. Terminal periods belong exclusively to complete spoken sentences in paragraphs.
  * Wrap text callouts in readable, high-contrast containers with dynamic bounds (`width: fit-content; max-width: 90vw; word-break: break-word; box-sizing: border-box;`).
  * Include distinct graphic elements across scenes:
    - Scene 1: Authentic product photo or clear illustrative hardware icon + bold headline title.
    - Scene 2: Problem context diagram or workflow illustration (e.g. Cloud vs Local edge data flow).
    - Scene 3: Technical architecture / NPU diagram or approved benchmark data callouts with sourced metrics.
    - Scene 4: Security / privacy shield or local memory architecture diagram with technical flow arrows.
    - Scene 5: Key takeaway visual, conclusion badge, and concise call to action.
- High-contrast typography: All headings, body text, badges, and metrics MUST use bright, highly readable colors on dark backgrounds (e.g. #ffffff for titles, #f8fafc for body text, #38bdf8 cyan or #fbbf24 amber for highlights). NEVER use black or dark grey text (#000, #1e293b, #333) on dark cards or backgrounds. All text must be clearly legible when rendered to video.
- CSS sizing must load fit-content; never use fixed width/height container constraints that silently clip dynamic text. Use CSS: `width: fit-content; max-width: 90vw; word-break: break-word; box-sizing: border-box; display: inline-block; padding: 10px 20px;`
- High-contrast visual plates ensuring the final composition meets strict 0.5000% edge-density QA gates.
- GSAP Scene Transitions & Audio-Visual Sync:
  * In script_vi.json, ensure exact non-overlapping section timestamps across 5 distinct scenes: intro (0.0s to 12.0s), context (12.0s to 26.0s), details (26.0s to 42.0s), impact (42.0s to 56.0s), conclusion (56.0s to 68.0s) totaling 60-75s.
  * In HTML & GSAP, every scene's entrance MUST strictly match its script section start time. If section 2 starts at 12.0s, scene 2 GSAP animations and entrance MUST start at 12.0s (NOT arbitrary or guessed times).
  * Scene 1 must stay visible until Scene 2 starts: e.g. `tl.to("#scene-1", {opacity: 0, duration: 0.3}, 12.0)`. NEVER fade out a scene before the next scene enters. A frame sampled at any random second must display rich headlines, cards, and text — NEVER a blank or black canvas.
- Layout & Footer Collision Prevention:
  * NEVER let tickers, status bars, or bottom chips overlap or collide with footer metadata, captions, or cards.
  * Reserve the bottom 16% of the portrait frame as a clear caption-safe rail on every scene; keep scene copy, tickers, footer metadata, and decorative plates above it.
  * Do not author static, estimated, or custom caption/subtitle elements. The pipeline installs validated audio-aligned ASR caption clips after generation; existing caption markup causes a fail-closed composition rejection.
  * Give `.meta`, footer elements, and the bottom of `.scene` adequate bottom padding (e.g. `margin-bottom: 90px;` or `padding-bottom: 120px;`) so all text remains completely clear and unclipped.
- Author deterministic, seek-safe GSAP only: create one master timeline with `gsap.timeline({ paused: true })`, add every animation to that timeline with `tl.to/from/fromTo/set`, and register it synchronously on `window.__timelines['main']`. Do not use standalone `gsap.to/from/fromTo/set`, `repeat: -1`, timers, async work, or unregistered timelines. Keep every timeline finite.
- Add purposeful, content-led movement only when it improves the story. Do NOT add decorative motion solely to evade the frozen-canvas check; do not promise motion on every frame. Motion must remain on the registered paused timeline and must not obscure or delay narration-aligned scene content.
- Do not read or set `tl.duration()` until all child animations have been added; preferably use the authored composition/scene duration as the source of truth. Do not derive scene timing from an incomplete timeline.
- Render contract:
  * The composition root element MUST carry `data-composition-id="main"`.
  * Register the fully constructed GSAP master timeline on `window.__timelines['main']` (e.g. `window.__timelines = window.__timelines || {}; window.__timelines['main'] = tl;`) so the runtime can drive playback.
  * Scene visibility and opacity transitions must be children of that same registered timeline. Preserve each script section's exact start time; use explicit timeline positions for scene entrances and exits. Never leave a scene hidden before the next scene is visible.

