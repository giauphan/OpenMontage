Mode: Bounded Artifact Repair

Repair incomplete or invalid outputs for {{PROJECT_DIR}} only. Read the current files and {{PROJECT_DIR}}/artifacts/research_brief.json first. Do not invoke pipeline wrappers, renderers, publishers, schedulers, social APIs, SSH, subagents, or background work. Do not accept stale files as success.

Repair only these artifacts:
- {{PROJECT_DIR}}/artifacts/script_vi.json
- {{PROJECT_DIR}}/hyperframes/index.html
- {{PROJECT_DIR}}/hyperframes_reels/index.html

Preserve valid content. Fix missing schema keys, malformed JSON, missing portrait roots, missing scene/timeline registration, broken relative assets, invalid Reels duration, Vietnamese text defects, low-contrast text (must be bright #fff/#f8fafc on dark cards), scene transition gaps (no empty frames), repetitive layouts, and forbidden visible branding. Ensure every scene's GSAP entrance matches script_vi.json section start_seconds so visual transitions are strictly aligned with narration audio. Keep ticker/status bars from overlapping footer metadata or text. Keep output self-contained and compatible with the existing HyperFrames renderer. Do not change providers, models, runtimes, or source material.


Finish synchronously and verify:
test -s "{{PROJECT_DIR}}/artifacts/script_vi.json" && test -s "{{PROJECT_DIR}}/hyperframes/index.html" && test -s "{{PROJECT_DIR}}/hyperframes_reels/index.html"

Return exactly one final status line:
- DIRECTOR_REPAIR_OK project={{PROJECT_DIR}}
- DIRECTOR_REPAIR_FAILED project={{PROJECT_DIR}} reason=<concise reason>
