Mode: Initial Generation

Generate or repair all three director outputs for {{PROJECT_DIR}}.

1. script_vi.json
Must be a flat JSON file at {{PROJECT_DIR}}/artifacts/script_vi.json (do not embed inside checkpoint).
Schema keys: version (1.0), title, total_duration_seconds, sections (array of: id, text, start_seconds, end_seconds).
Content: 100% correct Vietnamese spelling, exact grammatical tone marks, correct technical terminology. Rich spoken-word narration, 150-250 spoken words total (45-60s expected spoken duration). No dead air. Use a strong 3-second hook.

2. hyperframes/index.html & hyperframes_reels/index.html
hyperframes/index.html: The complete story with no sections/narration removed. Portrait 1080x1920 CSS layout. Duration matches the full text.
hyperframes_reels/index.html: Identical structure but shortened to <=60s for Instagram Reels.
Content & Quality for both:
- NO visible "Montage" or "OpenMontage" branding anywhere.
- Grounding: Base the narration and on-screen text 100% on the factual technology news in {{PROJECT_DIR}}/artifacts/research_brief.json. Do not invent unrelated numbers or generic filler.
- Visual scene diversity: Deliver at least 4 visually distinct scenes with varied editorial layouts:
  * Scene 1: Hero breaking news headline with category badge, high-contrast title, and glowing accent.
  * Scene 2: Key data/stats plate with numeric callouts, metric badges, or comparison points.
  * Scene 3: Deep-dive insight card, direct quote, tech architecture, or context breakdown.
  * Scene 4: Future impact / key takeaway summary callout with actionable conclusion.
- High-contrast typography: All headings, body text, badges, and metrics MUST use bright, highly readable colors on dark backgrounds (e.g. #ffffff for titles, #f8fafc for body text, #38bdf8 cyan or #fbbf24 amber for highlights). NEVER use black or dark grey text (#000, #1e293b, #333) on dark cards or backgrounds. All text must be clearly legible when rendered to video.
- CSS sizing must load fit-content; never use fixed width/height container constraints that silently clip dynamic text. Use CSS: `width: fit-content; max-width: 90vw; word-break: break-word; box-sizing: border-box; display: inline-block; padding: 10px 20px;`
- High-contrast visual plates ensuring the final composition meets strict 0.5000% edge-density QA gates.
- GSAP Scene Transitions & Audio-Visual Sync:
  * In script_vi.json, ensure exact non-overlapping section timestamps (e.g. section 1: 0.0s to 14.0s, section 2: 14.0s to 30.0s, section 3: 30.0s to 45.0s, section 4: 45.0s to 60.0s).
  * In HTML & GSAP, every scene's entrance MUST strictly match its script section start time. If section 2 starts at 14.0s, scene 2 GSAP animations and entrance MUST start at 14.0s (NOT arbitrary or guessed times).
  * Scene 1 must stay visible until Scene 2 starts: e.g. `tl.to("#scene-1", {opacity: 0, duration: 0.3}, 14.0)`. NEVER fade out a scene before the next scene enters. A frame sampled at any random second must display rich headlines, cards, and text — NEVER a blank or black canvas.
- Layout & Footer Collision Prevention:
  * NEVER let tickers, status bars, or bottom chips overlap or collide with footer metadata, captions, or cards.
  * Give `.meta`, footer elements, and the bottom of `.scene` adequate bottom padding (e.g. `margin-bottom: 90px;` or `padding-bottom: 120px;`) so all text remains completely clear and unclipped.
- Add a slow, continuous background/layer movement spanning the entire duration of every scene to prevent failure of the frozen-canvas check (max 50% static frames). Do NOT use <video> elements or CSS @keyframes for this; use only GSAP.

