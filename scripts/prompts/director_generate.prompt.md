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
- Must contain at least 4 distinct visual scenes (max 8s each).
- CSS sizing must load fit-content; never use fixed width/height container constraints that silently clip dynamic text. Use CSS: `width: fit-content; max-width: 90vw; word-break: break-word; box-sizing: border-box; display: inline-block; padding: 10px 20px;`
- High-contrast visual plates ensuring the final composition meets strict 0.5000% edge-density QA gates.
- Animate elements using only GSAP from CDN: <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>. The root container must have data-composition-id="main". Expose the timeline: `window.__timelines = window.__timelines || {}; const tl = gsap.timeline({paused: true}); window.__timelines['main'] = tl;`
- Add a slow, continuous background/layer movement spanning the entire duration of every scene to prevent failure of the frozen-canvas check (max 50% static frames). Do NOT use <video> elements or CSS @keyframes for this; use only GSAP.
