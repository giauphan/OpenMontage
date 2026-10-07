# MASTER PLAN — Multi‑Shot AI Video Generation Pipeline

## 0. Document status

**Purpose:** Design and implement a production-ready feature that can generate a long AI video from **2 or more independently generated video clips**, preserve character/style continuity, and assemble the final result automatically.

**Primary target durations**
- Short: 15–30 seconds
- Medium: 30–60 seconds
- Long: 60–120 seconds
- The architecture MUST NOT assume a fixed number of shots.

**Core rule**
> Treat every AI video generation request as stateless.
> The application owns story memory and continuity; the video model is only a renderer for the current shot.

---

# 1. Product Goal

Build a pipeline that accepts a topic/story request and produces:

1. A structured story.
2. A reusable character/style bible.
3. A shot plan with 2..N shots.
4. A keyframe/reference package for every shot.
5. One AI video request per shot.
6. One normalized `.mp4` per successful shot.
7. A final concatenated video.
8. Optional narration, music, SFX, subtitles, and captions.
9. Machine-readable manifest and validation reports.

The feature MUST support:
- Minimum 2 shots.
- Arbitrary N shots.
- Different shot durations.
- Retry of a single failed shot without regenerating the entire project.
- Regeneration of a single shot while preserving project identity.
- Resume from an interrupted run.
- Deterministic shot ordering.
- Final duration validation.

---

# 2. Non-Goals for V1

Do NOT make V1 depend on:
- Long-video generation in a single model request.
- Hidden memory inside the AI provider.
- Automatic frame-to-frame chaining from the previous clip only.
- A Python video-editing library for final encoding.
- Crossfade transitions between every shot.
- Real-time preview editing.

V1 SHOULD use:
- Python for orchestration.
- FFmpeg/ffprobe for media processing.
- AI image/video APIs for generation.

---

# 3. High-Level Architecture

```text
User Topic / Prompt
        |
        v
Story Planner
        |
        +--> story.json
        +--> character_bible.json
        +--> style_bible.json
        |
        v
Shot Planner
        |
        +--> shot_plan.json
        |
        v
Reference / Keyframe Generator
        |
        +--> references/character_master.*
        +--> keyframes/shot_001.*
        +--> keyframes/shot_002.*
        +--> ...
        |
        v
Prompt Builder
        |
        +--> prompts/shot_001.txt
        +--> prompts/shot_002.txt
        +--> ...
        |
        v
AI Video Job Manager
        |
        +--> raw/shot_001.mp4
        +--> raw/shot_002.mp4
        +--> ...
        |
        v
Media Validator + Normalizer
        |
        +--> normalized/shot_001.mp4
        +--> normalized/shot_002.mp4
        +--> ...
        |
        v
Timeline Assembler
        |
        +--> final/base_concat.mp4
        |
        +--> narration.wav
        +--> music.wav
        +--> subtitles.ass
        |
        v
Final FFmpeg Master
        |
        +--> final/final_video.mp4
        +--> reports/final_validation.json
```

---

# 4. Strict Design Principles

## 4.1 Stateless AI requests

Every shot prompt MUST independently contain enough information to render the shot correctly.

Every video request MUST include:

- Project title.
- Topic.
- Story summary.
- Visual style.
- Character lock.
- Environment lock.
- Continuity state.
- Current shot.
- Ending state.
- Negative constraints.
- Reference image(s), if supported.

Never assume:
- "The model remembers shot 1."
- "The model knows what Mochi looked like before."
- "The model remembers which objects were already broken."

---

## 4.2 Project-owned memory

Persistent project state MUST be stored in files or a database.

Required project memory:

```text
story.json
character_bible.json
style_bible.json
shot_plan.json
continuity_state.json
run_manifest.json
```

The model MUST receive relevant state on every request.

---

## 4.3 Shot-first design

The system MUST plan in shots, not only scenes.

Recommended defaults:

- 1 shot: 3–8 seconds.
- 1 scene: 1–4 shots.
- 30-second video: approximately 5–8 shots.
- 2-minute video: approximately 15–25 shots.

These are defaults, not hard limits.

A scene that needs 15 seconds SHOULD be split:

```text
Scene 3
  Shot 3A: 4 s
  Shot 3B: 5 s
  Shot 3C: 4 s
  Shot 3D: 2 s
```

Do not request one overloaded 15-second clip when multiple controlled shots are safer.

---

# 5. Project Directory Contract

```text
projects/<project_id>/
├── input/
│   └── request.json
├── planning/
│   ├── story.json
│   ├── character_bible.json
│   ├── style_bible.json
│   ├── shot_plan.json
│   └── continuity_state.json
├── references/
│   ├── character_master.png
│   ├── environment_master.png
│   └── props/
├── keyframes/
│   ├── shot_001.png
│   ├── shot_002.png
│   └── ...
├── prompts/
│   ├── shot_001.txt
│   ├── shot_002.txt
│   └── ...
├── jobs/
│   ├── shot_001.json
│   ├── shot_002.json
│   └── ...
├── raw/
│   ├── shot_001.mp4
│   ├── shot_002.mp4
│   └── ...
├── normalized/
│   ├── shot_001.mp4
│   ├── shot_002.mp4
│   └── ...
├── audio/
│   ├── narration.wav
│   ├── music.wav
│   └── sfx/
├── subtitles/
│   └── subtitles.ass
├── final/
│   ├── base_concat.mp4
│   └── final_video.mp4
├── reports/
│   ├── shot_validation.json
│   └── final_validation.json
└── run_manifest.json
```

Rules:
- A run MUST never overwrite another project.
- Every shot ID MUST be stable.
- Files MUST be named from the shot ID, not array position alone.
- A failed shot MUST remain traceable.

---

# 6. Pipeline Stages

## Stage 0 — Validate input

Input example:

```json
{
  "topic": "A funny orange cat tries to cook noodles",
  "target_duration_sec": 30,
  "aspect_ratio": "9:16",
  "resolution": "1080x1920",
  "fps": 30,
  "language": "vi",
  "min_shots": 2,
  "max_shots": 8
}
```

Strict validation:
- `topic` MUST be non-empty.
- `target_duration_sec` MUST be > 0.
- `min_shots` MUST be >= 2.
- `max_shots` MUST be >= `min_shots`.
- Reject invalid aspect ratio/resolution combinations.
- Do not begin paid AI jobs before validation passes.

Output:
- `input/request.json`

---

## Stage 1 — Generate story structure

Planner outputs:
- Title.
- Story premise.
- Beginning.
- Escalation.
- Climax.
- Resolution/punchline.
- Character list.
- Environment.
- Important props.
- Continuity-critical events.

Output:
- `planning/story.json`

Fail if:
- No clear narrative.
- No main character.
- Story cannot be divided into at least 2 shots.

---

## Stage 2 — Character Bible

Must define immutable identity fields:

```text
name
species/type
age appearance
body shape
face shape
eyes
hair/fur
color palette
clothing
accessories
unique markings
personality
movement style
forbidden changes
```

The system SHOULD distinguish:

### Locked fields
Cannot change unless story explicitly requires it.

### Mutable state
Can change through continuity:
- dirty face
- wet clothes
- torn sleeve
- emotional state
- held object

Output:
- `planning/character_bible.json`

---

## Stage 3 — Style Bible

Must define:
- 2D/3D/live-action/etc.
- Rendering style.
- Lighting.
- Color treatment.
- Lens/camera language.
- Motion style.
- Comedy/drama pacing.
- Environment detail level.
- Negative visual rules.
- Output framing.
- No-logo/no-watermark rules.

Output:
- `planning/style_bible.json`

---

## Stage 4 — Shot Planner

Planner MUST produce 2..N ordered shots.

Each shot MUST include:

```text
id
scene_id
order
duration_sec
location
time_of_day
characters
start_state
action
expression
camera
motion
props
dialogue/narration
end_state
transition_out
continuity_in
continuity_out
reference_requirements
```

Hard rules:
- Sum of planned durations SHOULD be close to target duration.
- No shot may depend on implicit provider memory.
- A shot MUST have a defined end state.
- The next shot MUST explicitly consume relevant prior state.
- One shot SHOULD contain one dominant action.
- Split overloaded shots.

Output:
- `planning/shot_plan.json`

---

## Stage 5 — Build reference assets

Preferred order:

```text
character master reference
        +
environment reference
        +
shot-specific keyframe
```

If provider accepts only one image:
1. Prefer shot-specific keyframe that already contains locked character identity.
2. Keyframe generator MUST use character master as input.

If provider supports multiple references:
- Send master character reference.
- Send shot keyframe.
- Optionally send environment reference.

Outputs:
- `references/*`
- `keyframes/shot_XXX.png`

Fail closed if:
- Required reference is missing.
- Wrong shot ID.
- Image unreadable.
- Character identity validation fails.

---

## Stage 6 — Build a full prompt per shot

Do NOT send only the current action.

Every generated prompt MUST contain:

```text
PROJECT
TOPIC
STORY SUMMARY
VISUAL STYLE
CHARACTER LOCK
ENVIRONMENT LOCK
CONSISTENCY RULES
CURRENT CONTINUITY STATE
CURRENT SHOT
ENDING FRAME
NEGATIVE CONSTRAINTS
```

Prompt template is defined in `02_DATA_CONTRACTS_AND_PROMPTS.md`.

Output:
- `prompts/shot_XXX.txt`

---

## Stage 7 — Submit video jobs

Job manager responsibilities:
- Submit 2..N jobs.
- Respect provider concurrency.
- Store provider job ID.
- Poll job state.
- Timeout.
- Retry retryable failures.
- Stop retrying permanent failures.
- Download finished clips.
- Verify file exists and size > 0.

Recommended V1 concurrency:
- Configurable.
- Default 2–3 simultaneous jobs.
- Do NOT hardcode unlimited parallel requests.

Per-shot states:

```text
PLANNED
KEYFRAME_READY
PROMPT_READY
SUBMITTED
RUNNING
DOWNLOADING
DOWNLOADED
VALIDATING
NORMALIZED
FAILED_RETRYABLE
FAILED_PERMANENT
```

Output:
- `jobs/shot_XXX.json`
- `raw/shot_XXX.mp4`

---

## Stage 8 — Validate every clip

Use ffprobe.

Validate:
- Video stream exists.
- Duration > 0.
- Resolution readable.
- FPS readable.
- Codec readable.
- No corrupt container.
- Duration within configured tolerance.
- File size above minimum threshold.

Optional visual checks:
- black frame ratio
- frozen frame ratio
- duplicated-frame ratio
- reference similarity
- NSFW/safety policy checks where required

A clip that fails MUST NOT enter final concat.

Output:
- `reports/shot_validation.json`

---

## Stage 9 — Normalize clips

Canonical V1 target:

```text
1080x1920
30 fps
H.264
yuv420p
AAC if audio retained
```

Example conceptual FFmpeg filter:

```text
scale -> pad/crop -> fps -> pixel format -> encode
```

Every normalized output MUST have:
- Same resolution.
- Same FPS.
- Same codec.
- Same pixel format.
- Compatible audio layout.

Output:
- `normalized/shot_XXX.mp4`

---

## Stage 10 — Concatenate

Preferred default:
- Hard cuts.

Do not add transitions automatically unless specified.

Create ordered concat list from `shot_plan.json`, never from filesystem sorting alone.

Example:

```text
file 'shot_001.mp4'
file 'shot_002.mp4'
file 'shot_003.mp4'
```

Output:
- `final/base_concat.mp4`

Strict rules:
- Missing shot = fail finalization.
- Duplicate shot = fail.
- Wrong order = fail.
- Concatenated duration MUST approximately equal the sum of normalized shots.

---

## Stage 11 — Audio / captions

Optional layers:
- Narration.
- Background music.
- SFX.
- Subtitle file.
- Burned-in captions.

Audio pipeline MUST define:
- target LUFS
- narration priority
- music ducking
- fade in/out
- silence handling

Do not assume generated shot audio is usable.

---

## Stage 12 — Final render

Inputs:
- `base_concat.mp4`
- optional narration
- optional music
- optional SFX
- optional subtitles

Output:
- `final/final_video.mp4`

Use FFmpeg as the final media engine.

---

## Stage 13 — Final validation

Required checks:
- Final file exists.
- Final file > minimum size.
- Duration within tolerance.
- Target resolution correct.
- FPS correct.
- Video stream decodable.
- Audio stream valid when expected.
- No missing shot.
- Shot count >= 2.
- Order correct.

Output:
- `reports/final_validation.json`

Only mark project `COMPLETED` if every mandatory check passes.

---

# 7. Continuity Engine

Continuity MUST be explicit.

Example:

```json
{
  "after_shot_id": "shot_004",
  "character": {
    "Mochi": {
      "clothing": {
        "chef_hat": "crooked",
        "apron": "cream, lightly covered with flour"
      },
      "face": "light flour dust",
      "mood": "embarrassed",
      "held_objects": []
    }
  },
  "environment": {
    "kitchen_counter": "messy with flour",
    "floor": "slightly wet",
    "stove": "on"
  },
  "objects": {
    "mixing_bowl": "on counter",
    "flour_bag": "fallen sideways"
  }
}
```

Rules:
- State updates occur only after a shot is accepted.
- Retry of the same shot uses the same `continuity_in`.
- Regenerating a prior accepted shot MAY invalidate later states.
- If an earlier end-state changes materially, downstream shots MUST be marked `STALE`.

---

# 8. Retry Strategy

Retryable:
- API timeout.
- HTTP 429.
- HTTP 5xx.
- Provider transient failure.
- Download interrupted.
- Corrupt download.
- Clip duration slightly wrong, if provider supports regeneration.

Permanent:
- Invalid auth.
- Unsupported model/input.
- Safety refusal.
- Invalid reference format.
- User quota exhausted unless quota may reset later.

Recommended:
- Exponential backoff.
- Jitter.
- Max attempts configurable.
- Store every attempt in job metadata.

Never silently replace a failed shot with an unrelated generated clip.

---

# 9. Resume / Idempotency

Every pipeline stage MUST be resumable.

On restart:
- Reuse valid completed assets.
- Re-run only missing/invalid stages.
- Do not resubmit finished AI jobs.
- Do not normalize an already valid normalized clip.
- Do not regenerate references unless source parameters changed.

Each stage SHOULD compute an input hash.

Example:
- Prompt changed → invalidate video job for that shot.
- Keyframe changed → invalidate video job for that shot.
- Shot video changed → invalidate normalized clip and final concat.
- Music changed → keep generated video clips, only rebuild final audio/master stage.

---

# 10. Suggested Python Modules

```text
src/
├── config.py
├── models/
│   ├── project.py
│   ├── story.py
│   ├── shot.py
│   ├── continuity.py
│   └── jobs.py
├── planning/
│   ├── story_planner.py
│   ├── shot_planner.py
│   └── continuity_engine.py
├── prompting/
│   └── shot_prompt_builder.py
├── providers/
│   ├── base_video_provider.py
│   ├── base_image_provider.py
│   └── ...
├── generation/
│   ├── keyframe_generator.py
│   └── video_job_manager.py
├── media/
│   ├── ffprobe.py
│   ├── normalize.py
│   ├── concat.py
│   ├── audio.py
│   └── final_render.py
├── validation/
│   ├── shot_validator.py
│   └── final_validator.py
├── orchestration/
│   └── pipeline.py
└── cli.py
```

---

# 11. Provider Abstraction

Use an interface such as:

```python
class VideoProvider:
    async def submit(self, prompt, references, duration_sec, config):
        ...

    async def get_status(self, job_id):
        ...

    async def download(self, job_id, destination):
        ...
```

Pipeline code MUST NOT directly depend on one vendor API.

Provider adapter owns:
- Auth.
- Provider-specific request fields.
- Polling semantics.
- Status mapping.
- Download URL extraction.
- Error translation.

---

# 12. Concurrency Rules

Config:

```json
{
  "max_video_jobs_in_flight": 3,
  "max_downloads_in_flight": 3,
  "max_retries": 3
}
```

Rules:
- Never submit all N requests blindly.
- Use a bounded semaphore.
- Poll efficiently.
- Preserve shot ordering independently from completion ordering.
- A later shot may finish first; final assembly still follows shot plan order.

---

# 13. Security / Cost Controls

Before paid generation:
- Validate project.
- Validate shot count.
- Estimate number of provider calls.
- Estimate retries.
- Enforce max cost/job if possible.

Never log:
- API secrets.
- Signed provider URLs if they contain secrets.
- User private credentials.

Record:
- provider
- model
- job ID
- duration requested
- attempts
- status
- cost metadata if available

---

# 14. CLI Proposal

```bash
python -m app create-project request.json

python -m app plan <project_id>

python -m app generate-keyframes <project_id>

python -m app generate-videos <project_id>

python -m app validate-shots <project_id>

python -m app normalize <project_id>

python -m app assemble <project_id>

python -m app finalize <project_id>

python -m app run <project_id>

python -m app retry-shot <project_id> shot_004

python -m app regenerate-shot <project_id> shot_004

python -m app status <project_id>
```

`run` SHOULD execute all required stages safely.

---

# 15. Mandatory Logging

Every log line SHOULD include:
- timestamp
- project_id
- stage
- shot_id where applicable
- provider job ID where applicable
- attempt
- status
- error class

Example:

```text
2026-10-05T13:00:00Z project=p123 stage=video_generate shot=shot_004 attempt=2 status=RUNNING provider_job=j_abc
```

---

# 16. Failure Policy

**Fail closed.**

Do NOT publish/finalize if:
- A required shot is missing.
- A clip is corrupt.
- Order cannot be established.
- Final duration is invalid.
- Final resolution is invalid.
- Required references are missing.
- `shot_count < 2`.

Partial assets remain on disk for resume/debug.

---

# 17. Definition of Done — Feature Level

The feature is DONE only if all are true:

- [ ] Accepts a project with at least 2 shots.
- [ ] Supports N shots without hardcoded fixed count.
- [ ] Creates structured story/character/style/shot files.
- [ ] Creates one complete prompt per shot.
- [ ] Each shot can be generated independently.
- [ ] Uses the same character/style references consistently.
- [ ] Stores continuity state explicitly.
- [ ] Retries transient failures.
- [ ] Can resume a partially completed project.
- [ ] Downloads each generated clip.
- [ ] Validates clips using ffprobe.
- [ ] Normalizes all clips.
- [ ] Concatenates in deterministic shot order.
- [ ] Supports narration/music/subtitles as optional post-processing.
- [ ] Produces final MP4.
- [ ] Produces machine-readable validation report.
- [ ] A failed shot prevents invalid final completion.
- [ ] Individual shot regeneration is supported.
- [ ] Unit + integration + end-to-end tests pass.

---

# 18. Recommended Implementation Order

## Milestone 1 — Skeleton
- Project directory.
- Pydantic/dataclass schemas.
- Manifest/state machine.
- CLI.

## Milestone 2 — Planning
- Story schema.
- Character/style bible.
- Shot planner.
- Continuity state.

## Milestone 3 — Prompt generation
- Prompt template.
- Prompt builder.
- Snapshot tests.

## Milestone 4 — Provider integration
- Base provider.
- One real provider adapter.
- Submit/poll/download.
- Retry and concurrency.

## Milestone 5 — FFmpeg pipeline
- ffprobe wrapper.
- Normalize.
- Ordered concat.
- Final render.

## Milestone 6 — Resume + invalidation
- Input hashes.
- Stage caching.
- Stale downstream detection.

## Milestone 7 — Quality
- Validation reports.
- E2E multi-shot test.
- Documentation.
- Cost/metrics.

---

# 19. First Production Acceptance Scenario

Input:
- Topic: funny orange cat cooks noodles.
- Duration: 30 seconds.
- 6 shots.
- 9:16.
- 1080x1920.
- 30 fps.

Expected:
- 6 prompts.
- 6 keyframes.
- 6 AI video jobs.
- 6 raw MP4s.
- 6 validated normalized MP4s.
- 1 concatenated base.
- 1 final MP4.
- Continuity preserved:
  - same cat identity
  - same clothes
  - environment damage persists across shots
- Re-run after deleting only `shot_004.mp4` regenerates only shot 4 and dependent media outputs.

This scenario MUST pass before calling V1 ready.
