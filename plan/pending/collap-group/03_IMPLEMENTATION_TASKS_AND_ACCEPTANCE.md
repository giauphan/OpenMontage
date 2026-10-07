# IMPLEMENTATION TASKS, TEST MATRIX & ACCEPTANCE GATES

Use this as the execution checklist for the feature.

---

# 1. Epic: Multi-Shot AI Video Pipeline

## Goal

Generate a final video from **2 or more AI-generated video files**, without depending on provider memory, while preserving character/style/continuity and supporting retry/resume.

---

# 2. Task Breakdown

## TASK 001 — Project schemas

Implement:
- request schema
- story schema
- character bible schema
- style bible schema
- shot plan schema
- continuity state schema
- job schema
- run manifest schema

Acceptance:
- invalid min_shots < 2 rejected
- duplicate shot IDs rejected
- duplicate shot order rejected
- missing end_state rejected
- valid 2-shot plan accepted
- valid 25-shot plan accepted

---

## TASK 002 — Project workspace

Implement deterministic project directories.

Acceptance:
- new project produces required folders
- existing project not overwritten accidentally
- safe path handling
- stable shot filenames

---

## TASK 003 — Story planner

Input:
- topic
- target duration
- style preferences

Output:
- `story.json`

Acceptance:
- has beginning/escalation/climax/resolution
- identifies main character
- identifies location/props
- supports decomposition into >= 2 shots

---

## TASK 004 — Character/style bible builder

Acceptance:
- immutable character fields separate from mutable state
- negative constraints included
- no shot prompt can be generated without a character lock for character-driven stories

---

## TASK 005 — Shot planner

Implement shot decomposition.

Acceptance:
- minimum 2 shots
- duration sum close to target
- each shot has exactly one dominant action
- each shot has start + end state
- overloaded actions split
- shot IDs stable across re-runs when plan unchanged

---

## TASK 006 — Continuity engine

Implement:
- continuity_in
- continuity_out
- accepted state
- version counter
- downstream stale detection

Acceptance:
- failed shot does not update continuity
- accepted shot updates continuity once
- retry uses identical continuity_in
- regenerate earlier shot with changed end state marks later shots stale

---

## TASK 007 — Prompt builder

Build one self-contained prompt per shot.

Required sections:
- project
- topic
- story summary
- style
- character lock
- environment lock
- continuity
- current shot
- ending state
- negative constraints

Acceptance:
- snapshot tests for shot 1, middle shot, last shot
- no template placeholder remains unresolved
- prompt contains shot ID and duration
- prompt contains full character identity

---

## TASK 008 — Reference/keyframe manager

Implement:
- master character reference
- optional environment reference
- per-shot keyframe
- metadata/hash tracking

Acceptance:
- video generation blocked when required reference absent
- changed reference invalidates dependent video job
- shot keyframe tied to correct shot ID

---

## TASK 009 — Video provider interface

Implement abstract adapter:
- submit
- poll
- download

Acceptance:
- fake provider unit test
- provider errors map to internal error codes
- no provider-specific logic leaks into orchestration

---

## TASK 010 — Video job scheduler

Implement bounded concurrency.

Acceptance:
- configured concurrency never exceeded
- jobs may finish out of order
- stored shot order remains unchanged
- rate-limit retries obey backoff
- permanent errors do not loop forever

---

## TASK 011 — Download manager

Acceptance:
- atomic downloads
- temp file on in-progress download
- incomplete download not treated as success
- valid response saved to `raw/shot_XXX.mp4`

---

## TASK 012 — ffprobe wrapper

Acceptance:
- extracts duration
- extracts resolution
- extracts FPS
- extracts codec/pixel format
- detects no-video file
- returns structured validation object

---

## TASK 013 — Shot validator

Acceptance:
- corrupt clip rejected
- 0-second clip rejected
- duration tolerance enforced
- missing clip rejected
- valid AI clip accepted

---

## TASK 014 — FFmpeg normalizer

Normalize all accepted clips to canonical format.

Acceptance:
- mixed source resolutions become 1080x1920
- mixed FPS become 30 fps
- output H.264/yuv420p
- clip remains decodable
- duration remains within tolerance

---

## TASK 015 — Ordered concat

Acceptance:
- reads ordering from shot plan
- not dependent on directory listing order
- hard cut default
- missing required shot fails
- duplicate shot fails
- final base duration approximately equals shot duration sum

---

## TASK 016 — Narration/music/SFX/subtitle layer

Acceptance:
- optional
- pipeline works with all audio disabled
- narration can be overlaid after video concat
- music ducking configuration available
- subtitle path optional
- changing music does not regenerate AI shots

---

## TASK 017 — Final master render

Acceptance:
- outputs `final/final_video.mp4`
- canonical video properties
- audio valid if enabled
- subtitles burned or muxed per config

---

## TASK 018 — Final validator

Acceptance:
- shot count >= 2
- every planned shot represented
- final duration tolerance passes
- final resolution/FPS passes
- no missing mandatory assets
- only then set project COMPLETED

---

## TASK 019 — Resume

Test scenario:
1. 6-shot project.
2. Shots 1–3 complete.
3. Process crashes while shot 4 running.
4. Restart.

Acceptance:
- shots 1–3 not regenerated
- running/incomplete job reconciled
- only remaining work continues
- final video produced after recovery

---

## TASK 020 — Single-shot retry

Scenario:
- shot 4 failed transiently.

Acceptance:
- retry shot 4 only
- shot 1–3 unchanged
- downstream concat rebuilt only after shot 4 valid

---

## TASK 021 — Single-shot regeneration

Scenario:
- user dislikes shot 4.

Acceptance:
- regenerate shot 4 with same locked character/style
- preserve continuity_in
- update continuity_out if materially changed
- mark downstream stale if required
- do not recreate unrelated earlier shots

---

# 3. Unit Test Matrix

| Test | Expected |
|---|---|
| min_shots = 1 | reject |
| min_shots = 2 | accept |
| 30 shots | accept if config allows |
| duplicate shot ID | reject |
| duplicate order | reject |
| missing character lock | reject prompt build |
| missing keyframe where required | block generation |
| provider 429 | retry |
| provider 401 | permanent fail |
| corrupt MP4 | reject |
| wrong FPS | normalize |
| wrong resolution | normalize |
| missing shot in concat | fail |
| job completion out of order | preserve planned timeline |
| restart after partial run | resume |
| changed music | only final stage invalidated |
| changed shot 4 prompt | invalidate shot 4 + downstream media |

---

# 4. Integration Tests

## IT-01 — Minimum 2-shot project

Generate:
- shot_001.mp4
- shot_002.mp4

Then:
- normalize
- concat
- final validate

Pass if:
- final video exists
- two shots appear in correct order
- duration approximately sum of both

---

## IT-02 — 6-shot 30-second project

Simulated provider is acceptable in CI.

Pass if:
- 6 distinct job records
- 6 clip files
- 6 normalized files
- exact ordering
- one final video
- no implicit AI memory dependency

---

## IT-03 — Mixed media inputs

Input clips:
- different FPS
- different codecs
- different resolutions

Pass if:
- normalized outputs identical in target media format
- concat succeeds

---

## IT-04 — Retry recovery

Provider behavior:
- shot 3 attempt 1 => 500
- shot 3 attempt 2 => success

Pass if:
- no duplicate final shot
- attempt history stored
- project completes

---

## IT-05 — Permanent single-shot failure

Provider:
- shot 4 always fails permanently.

Pass if:
- project not marked COMPLETED
- no invalid final concat
- successful other shots retained
- status becomes PARTIAL or FAILED per configured policy

---

## IT-06 — Resume after crash

Force process termination after 50% jobs complete.

Pass if:
- completed clips reused
- unfinished jobs resumed/reconciled
- duplicate provider submissions avoided where possible

---

# 5. End-to-End Acceptance Test

## E2E-01 — Mochi 30-second video

Project:
- 6 shots
- funny orange cat cooking noodles
- 9:16
- 1080x1920
- 30 fps

Must produce:

```text
planning/story.json
planning/character_bible.json
planning/style_bible.json
planning/shot_plan.json
planning/continuity_state.json

references/character_master.png

keyframes/shot_001.png
...
keyframes/shot_006.png

prompts/shot_001.txt
...
prompts/shot_006.txt

raw/shot_001.mp4
...
raw/shot_006.mp4

normalized/shot_001.mp4
...
normalized/shot_006.mp4

final/base_concat.mp4
final/final_video.mp4

reports/shot_validation.json
reports/final_validation.json
run_manifest.json
```

Manual visual acceptance:
- same Mochi identity across all shots
- same chef clothing unless story says otherwise
- kitchen layout remains recognizable
- mess/damage persists when continuity says so
- no unexplained resets
- cuts are intentional
- story understandable in timeline order

---

# 6. Fail-Closed Gates

Pipeline MUST stop finalization when any is true:

- shot_count < 2
- required shot missing
- required shot failed
- corrupt normalized clip
- unresolved shot order
- invalid final duration
- invalid final resolution
- invalid final FPS
- required reference missing
- unresolved prompt template variable

No "best effort final.mp4" if mandatory shot data is incomplete.

---

# 7. Performance / Concurrency Tests

Test:
- N = 20 mock shots
- max concurrency = 3

Pass if:
- at no point >3 generation jobs in flight
- memory use remains bounded
- final order still 1..20
- no race corrupts manifest

---

# 8. Observability Requirements

Metrics:
- project total time
- planning time
- average generation time/shot
- attempts/shot
- provider failure count
- normalization time
- final render time
- total raw duration
- final duration

Useful dimensions:
- provider
- model
- project ID
- shot ID
- error type

---

# 9. Strict PR Checklist

Before merge:

- [ ] Schemas versioned.
- [ ] No fixed `for range(6)` or other hardcoded shot count.
- [ ] All shot ordering derives from data.
- [ ] All provider calls are behind adapter.
- [ ] API keys excluded from logs.
- [ ] Retry policy tested.
- [ ] Resume tested.
- [ ] ffprobe validation tested.
- [ ] FFmpeg normalize tested.
- [ ] Concat with 2 shots tested.
- [ ] Concat with >2 shots tested.
- [ ] Failure of middle shot blocks finalization.
- [ ] Character lock included in every prompt.
- [ ] Continuity state included in every non-initial shot prompt.
- [ ] State update occurs only after accepted shot.
- [ ] Downstream invalidation rules implemented.
- [ ] Final validation report generated.
- [ ] Documentation updated.

---

# 10. Release Gate

V1 can be released only after:

1. Unit test suite passes.
2. Integration suite passes.
3. Minimum 2-shot real/provider test passes.
4. 6-shot 30-second real/provider test passes.
5. Forced provider error test passes.
6. Crash/resume test passes.
7. Regenerate-one-shot test passes.
8. Final output validates with ffprobe.
9. No invalid project can be marked COMPLETED.
10. API credentials do not appear in artifacts or logs.

---

# 11. Next Phase After V1

Possible V2 work:
- automatic visual similarity scoring against character reference
- automatic keyframe consistency review
- scene-to-scene camera continuity rules
- shot re-ranking / quality scoring
- user review checkpoint before paid generation
- provider fallback routing
- cost optimizer
- distributed queue
- cloud object storage
- database-backed job state
- web UI timeline editor
- automatic narration timing and shot-duration replanning
