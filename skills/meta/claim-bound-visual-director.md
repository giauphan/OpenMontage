# Proposed Skill: Claim-Bound Visual Director & Asset Quality

**Stage:** scene plan → asset acquisition/generation → actual frame inspection.  
**Inputs:** localized script beats, claim ledger, project style playbook, rights policy, media/tool capability inventory.  
**Outputs:** claim-to-scene/asset matrix, provenance, storyboard, scene-by-scene QA and screenshot samples.

## Storyboard rule
Every meaningful scene must **explain, demonstrate, compare or provide honest context**. Generic tech grid/gradient/cards are not proof of a feature. Reuse animation vocabulary where it helps style consistency, but not repetitive identical scene grammar.

## Evidence visual preference hierarchy
1. Actual creator-run demo/screen capture when legally/operationally possible (UI date/version logged, private data redacted).
2. Verified first-party media/screenshots with reuse permissions or documented policy basis.
3. Own diagrams, charts based on validated data and linked sources; label simulated UI/data as illustrative.
4. Permitted/licensed stock video/photo only if its factual role is neutral and it illustrates a concept, not proves a specific claim.
5. Original AI images if clearly illustrative, stylistically appropriate and not passed off as a real product UI/person/event. Determine realistic GenAI disclosure obligation.
6. If none qualifies, deliberately choose an honest minimalist explanation rather than fabricate evidence.

## Required per-scene manifest
```json
{
 "scene_id":"V03", "beat_id":"S03", "claim_ids":["C004"],
 "viewer_question":"What changed?", "visual_purpose":"show actual feature UI",
 "asset_kind":"screen_recording", "source_url":"https://example.invalid/source",
 "license_basis":"creator-recorded / approved-use", "asset_sha256":"<sha256>",
 "capture_timestamp":"ISO8601 with timezone", "product_version":"VERIFIED_VERSION",
 "text_overlay_language":"en-US", "aspect":"9:16", "safe_zone_checked":false,
 "render_frame_samples":[], "real_vs_illustrative":"real", "review_status":"pending"
}
```

## Creative direction
- Vary visual grammar with intent: full demo/zoom, side-by-side comparison, diagram with a progressive reveal, test summary and credible product UI. Cut visual as the idea changes, not every arbitrary few seconds.
- Use `lib/slideshow_risk.py`, `lib/variation_checker.py`, `lib/news_visual/*`; inspect their limitations and make failures actionable. A numerical heuristic cannot verify image-semantic correctness alone.
- Background should reflect content: UI/software claims → actual UI; technical concept → diagrams; cost claim → sourced figure; performance claim → reproducible benchmark shot. Do **not** decorate unrelated claims with stock server-room footage.
- Ensure icon and imagery are not misleading, copyrighted without permission, low resolution, stretched, watermarked or illegible on 9:16 screens. Neutral explanatory music never masks narration.
- Preview actual final MP4 frames for opening, critical claim, every distinct scene type, mid-point and ending; random sampling supplements predetermined samples.
- Text content, badge names, spellings and subtitles must match en-US script. Check mobile safe area and text density.

## Fail gates
- Missing/corrupt asset; unverified numbers on chart; unrelated generated visual; repeated generic cards dominating meaningful explanations; fake product UI; unknown or prohibited rights; static HTML looks fine but MP4 fails; wrong aspect; unreadable text; inconsistent spoken/screen claim.
- Generated visual changes source claim or simulates a real news event without appropriate label/rights review.

## QA contract
Return `PASS|REVISE|BLOCKED` per scene with rationale, source/asset ID, frame evidence paths, replacement type. Only rerun affected asset generation when upstream hashes unchanged, then re-render and revalidate downstream. Human/creative approval for canary mandatory.
