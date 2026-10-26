Mode: Initial Generation (en-US / US Market)

Generate or repair all three director outputs for {{PROJECT_DIR}}.

Target Audience & Cultural Localization:
- Audience: United States technology professionals, developers, and tech enthusiasts.
- Editorial Standard: Self-contained US English tech documentary standard (do NOT open or search external `skills/` or `scripts/` files).
- Voice & Tone: Confident, fast-paced, insightful, authoritative American tech documentary narration.
- Idiomatic Precision: Use natural American spoken English ("straightforward", "tradeoff", "under the hood", "step-by-step"). Avoid literal calques, machine-translation relics, or unnatural tropes.

1. script_en_US.json
Must be a flat JSON file at {{PROJECT_DIR}}/artifacts/script_en_US.json (do not embed inside checkpoint).
Schema keys: version (MUST be string "1.0", never number 1.0), title, total_duration_seconds, sections (array of: id, text, start_seconds, end_seconds).
Content: 100% natural, idiomatic American English. Rich spoken-word narration, 180-240 spoken words total (60-75s expected spoken duration, minimum 60s). No dead air. Use a strong 3-second hook that leads with the breakthrough or disruption. CRITICAL DURATION GOAL: Videos must reach at least 60 seconds (1 minute or more). Never write fewer than 180 English words. CRITICAL: NEVER truncate or cut off text mid-sentence or mid-word. Every section MUST be a complete, grammatically sound, fully articulated English sentence.

News evidence and factual grounding: Base all script content strictly on the technology news in {{PROJECT_DIR}}/artifacts/research_brief.json and any supplied frozen source excerpts. Map factual assertions strictly to verified claims in `research_brief.json`. Never invent citations, benchmark numbers, quotes, or product specifications.

2. hyperframes/index.html & hyperframes_reels/index.html
hyperframes/index.html: The complete story for 16:9 long-form video with no sections/narration removed. MUST use Landscape 1920x1080 layout everywhere: `<meta name="viewport" content="width=1920, height=1080">`, `#stage { width: 1920px; height: 1080px; position: relative; overflow: hidden; }`, and a closed direct child of `<body>`: `<div id="stage" data-composition-id="main" data-start="0" data-duration="<total_seconds>" data-width="1920" data-height="1080">...</div>`. Duration matches the full text (60-75s, minimum 60s).
hyperframes_reels/index.html: Identical story for 9:16 Shorts/Reels. MUST use Portrait 1080x1920 layout everywhere: `<meta name="viewport" content="width=1080, height=1920">`, `#stage { width: 1080px; height: 1920px; position: relative; overflow: hidden; }`, and a closed direct child of `<body>`: `<div id="stage" data-composition-id="main" data-start="0" data-duration="<total_seconds>" data-width="1080" data-height="1920">...</div>`.
Content & Quality for both:
- NO visible "Montage" or "OpenMontage" branding anywhere.
- Grounding: Base the narration and on-screen text 100% on the factual technology news in {{PROJECT_DIR}}/artifacts/research_brief.json.
- Visual scene diversity, visual intent & styling (MANDATORY):
  * Content-first visual intent: Every narrative beat must declare a clear visual_intent and evidence_class (e.g. authentic_photo, svg_diagram, contextual_icon, or typographic_focus).
  * For major technical concepts, hardware, or architecture, author an actual SVG diagram or bind an approved staged source image from assets/visuals/ — do NOT rely on text-only cards.
  * In visual mode, consume staged local files from assets/visuals/ or inline deterministic SVG layers.
  * Scene-specific art direction: Distinct scenes must have distinct, context-relevant visual treatment.
  * Layout & Non-Overlapping Elements (CRITICAL): Place headlines, body copy, metric cards, and SVG diagrams in normal document/flex/grid flow (`display: flex; flex-direction: column; gap: 28px;` or CSS Grid) with `position: relative`. NEVER use `position: absolute` with hardcoded `top:` / `right:` offsets for panels, cards, or `<svg>` elements inside `.scene`, as absolute-positioned diagrams will collide with and cover headlines or body text.
  * High-contrast typography: All headings, body text, badges, and metrics MUST use bright, highly readable colors on dark backgrounds (e.g. #ffffff for titles, #f8fafc for body text, #38bdf8 cyan or #fbbf24 amber for highlights). NEVER use black or dark grey text (#000, #1e293b, #333) on dark cards or backgrounds.
  * GSAP Scene Transitions & Audio-Visual Sync:
    - MUST load GSAP (`<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>`), synchronously create `const tl = gsap.timeline({ paused: true });`, attach all animations to `tl` via `tl.to/from/fromTo/set`, and register `window.__timelines = window.__timelines || {}; window.__timelines['main'] = tl;`. NEVER use `requestAnimationFrame` loops, `setInterval`, `setTimeout`, or custom non-GSAP timeline objects.
    - Every scene entrance matches its script section start time, AND every scene MUST include continuous finite motion across its entire duration (e.g. `tl.fromTo('#scene-1', { scale: 1.0 }, { scale: 1.04, y: -12, duration: 14, ease: 'none' }, 0)` plus staggered card/diagram tweens) so the canvas is never static for more than 2 seconds. Extend the final scene's continuous motion tween up to 110s so the video never freezes if TTS narration runs longer than estimated.
    - CRITICAL: Every scene MUST fade out (`opacity: 0` / `autoAlpha: 0`) right when the next scene begins so two scenes NEVER overlap on screen at the same time. Only ONE scene may be visible (`opacity > 0`) at any timestamp. Scene 1 stays visible until Scene 2 starts, then Scene 1 fades to `opacity: 0` as Scene 2 fades to `opacity: 1`. A frame sampled at any second displays rich headlines, cards, and diagrams — NEVER a blank canvas and NEVER overlapping scenes.
  * Caption rail reservation: Reserve bottom 16% of the frame as caption-safe zone. Do not author custom static captions or use class names `caption`, `captions`, `subtitle`, `subtitles`, or `id="caption-..."`; automated ASR captions are installed downstream.
