# DATA CONTRACTS, PROMPTS & STATE MACHINE

This document defines strict machine-readable contracts for the multi-shot AI video pipeline.

---

# 1. `request.json`

```json
{
  "project_id": "optional-client-id",
  "topic": "A funny orange cat tries to cook noodles",
  "target_duration_sec": 30,
  "language": "vi",
  "aspect_ratio": "9:16",
  "resolution": {
    "width": 1080,
    "height": 1920
  },
  "fps": 30,
  "shot_policy": {
    "min_shots": 2,
    "max_shots": 8,
    "preferred_min_duration_sec": 3,
    "preferred_max_duration_sec": 8
  },
  "audio": {
    "narration": true,
    "music": true,
    "sfx": true,
    "subtitles": true
  }
}
```

Hard validation:
- min_shots >= 2
- max_shots >= min_shots
- width > 0
- height > 0
- fps > 0
- target_duration_sec > 0

---

# 2. `story.json`

```json
{
  "title": "Mochi Cooking Disaster",
  "topic": "Funny cooking animation",
  "summary": "Mochi confidently cooks noodles, causes escalating chaos, then discovers the simple instructions.",
  "beats": [
    {
      "id": "beat_01",
      "type": "hook",
      "summary": "Mochi confidently starts cooking."
    },
    {
      "id": "beat_02",
      "type": "escalation",
      "summary": "Mistakes make the kitchen increasingly chaotic."
    },
    {
      "id": "beat_03",
      "type": "punchline",
      "summary": "Mochi discovers the simple instructions too late."
    }
  ],
  "characters": ["Mochi"],
  "locations": ["Kitchen"],
  "important_props": [
    "instant noodle packet",
    "pot",
    "chili bottle",
    "instruction card"
  ]
}
```

---

# 3. `character_bible.json`

```json
{
  "characters": [
    {
      "id": "char_mochi",
      "name": "Mochi",
      "role": "main",
      "locked_identity": {
        "type": "chubby orange cartoon cat",
        "body": "round body, short legs, tiny paws",
        "face": "round face",
        "eyes": "large green eyes",
        "fur": "orange with cream belly and muzzle",
        "markings": "consistent orange stripes",
        "clothing": [
          "oversized white chef hat",
          "small red apron"
        ]
      },
      "personality": [
        "overconfident",
        "clumsy",
        "curious",
        "dramatic",
        "adorable"
      ],
      "motion_style": [
        "exaggerated facial reactions",
        "squash and stretch",
        "expressive tail and ears"
      ],
      "forbidden_changes": [
        "do not change eye color",
        "do not change fur color",
        "do not change body proportions",
        "do not change clothing unless explicitly scripted",
        "do not add or remove markings"
      ]
    }
  ]
}
```

---

# 4. `style_bible.json`

```json
{
  "visual_style": "high-quality colorful 3D cartoon animation",
  "lighting": "bright warm cinematic lighting",
  "camera_language": [
    "reaction close-ups",
    "medium comedy shots",
    "wide shots for chaos",
    "quick push-ins before punchlines"
  ],
  "motion": [
    "continuous visible movement",
    "squash and stretch",
    "secondary motion on ears, tail, clothing and props"
  ],
  "color": "bright cheerful saturated palette",
  "render_rules": [
    "consistent character identity",
    "consistent environment layout",
    "no flickering",
    "no character morphing",
    "no duplicated limbs",
    "no watermark",
    "no logo"
  ]
}
```

---

# 5. `shot_plan.json`

```json
{
  "target_duration_sec": 30,
  "shots": [
    {
      "id": "shot_001",
      "scene_id": "scene_01",
      "order": 1,
      "duration_sec": 5,
      "location": "Kitchen",
      "characters": ["char_mochi"],
      "start_state": {
        "character": "Mochi clean, chef hat straight",
        "environment": "clean kitchen"
      },
      "action": "Mochi confidently slams a noodle packet onto the counter.",
      "expression": "smug confidence",
      "camera": "medium close-up with quick push-in",
      "motion": "fast paw slam, ears bounce, tail flick",
      "props": ["instant noodle packet", "pot"],
      "end_state": {
        "character": "Mochi shocked by a popping pot lid",
        "environment": "kitchen still clean",
        "props": {
          "pot": "lid lifted briefly"
        }
      },
      "transition_out": "hard_cut"
    }
  ]
}
```

Validation rules:
- IDs unique.
- `order` unique.
- `duration_sec > 0`.
- At least 2 shots.
- No gaps/duplicates in planned order unless explicitly supported.
- Every shot has `start_state` and `end_state`.

---

# 6. `continuity_state.json`

Recommended model:

```json
{
  "version": 7,
  "accepted_through_shot": "shot_004",
  "character_state": {
    "char_mochi": {
      "clothing_state": {
        "chef_hat": "crooked",
        "red_apron": "lightly stained"
      },
      "body_state": {
        "fur": "slightly messy",
        "face": "light flour dust"
      },
      "emotion": "embarrassed",
      "held_objects": []
    }
  },
  "environment_state": {
    "kitchen": {
      "counter": "messy",
      "floor": "slightly wet",
      "stove": "on"
    }
  },
  "object_state": {
    "flour_bag": "fallen sideways",
    "mixing_bowl": "on counter"
  }
}
```

Mutation rules:
1. Load `continuity_in`.
2. Generate shot.
3. Validate shot.
4. Only if accepted, apply `continuity_out`.
5. Increment version.
6. Persist atomically.

Never update continuity from a failed generation.

---

# 7. Shot Prompt Template

```text
PROJECT:
{{project_title}}

TOPIC:
{{topic}}

STORY SUMMARY:
{{story_summary}}

VISUAL STYLE:
{{visual_style}}

CHARACTER LOCK:
Main character: {{character_name}}
Identity: {{locked_identity}}
Personality: {{personality}}
Movement style: {{movement_style}}
Forbidden changes: {{forbidden_character_changes}}

ENVIRONMENT LOCK:
{{environment_description}}

CONSISTENCY RULES:
- Keep the exact same character identity.
- Preserve body proportions, colors, face, eyes, markings and clothing.
- Preserve the established environment layout.
- Preserve continuity state from previous accepted shots.
- Do not introduce new characters or major props unless explicitly listed.
- Do not silently repair or reset damage/mess from prior shots.

CURRENT CONTINUITY STATE:
Previous accepted shot: {{previous_shot_id}}
Character state: {{character_state}}
Environment state: {{environment_state}}
Object state: {{object_state}}

CURRENT SHOT:
Shot ID: {{shot_id}}
Duration: {{duration_sec}} seconds
Location: {{location}}
Action: {{action}}
Expression: {{expression}}
Camera: {{camera}}
Motion: {{motion}}
Props: {{props}}

ENDING FRAME / REQUIRED END STATE:
{{end_state}}

NEGATIVE CONSTRAINTS:
- no character redesign
- no costume changes
- no eye-color changes
- no duplicated limbs
- no extra fingers/paws
- no morphing
- no flicker
- no watermark
- no logos
- no unrelated background changes
{{provider_specific_negative_constraints}}
```

Strict rule:
- The prompt builder MUST NOT omit the character lock or current continuity state.
- For shot 1, use explicit initial state instead of "none".

---

# 8. `job` record

```json
{
  "shot_id": "shot_004",
  "provider": "provider_name",
  "model": "model_name",
  "provider_job_id": "abc123",
  "status": "RUNNING",
  "attempt": 2,
  "max_attempts": 3,
  "submitted_at": "2026-10-05T13:00:00Z",
  "updated_at": "2026-10-05T13:01:00Z",
  "input_hash": "sha256:...",
  "error": null
}
```

---

# 9. Project State Machine

Project states:

```text
CREATED
PLANNED
REFERENCES_READY
GENERATING
PARTIAL
SHOTS_READY
NORMALIZED
ASSEMBLED
FINALIZING
COMPLETED
FAILED
```

Allowed high-level transitions:

```text
CREATED
  -> PLANNED
  -> REFERENCES_READY
  -> GENERATING
  -> SHOTS_READY
  -> NORMALIZED
  -> ASSEMBLED
  -> FINALIZING
  -> COMPLETED
```

`PARTIAL`:
- At least one shot succeeded.
- At least one required shot incomplete or failed.

`FAILED`:
- Permanent unrecoverable failure OR explicit max retry exhaustion.

A project with a missing required shot MUST NOT transition to `ASSEMBLED`.

---

# 10. Invalidation Rules

If changed:

### Story only, no shot plan change
- Recompute affected shot prompts.

### Character bible
Invalidate:
- keyframes
- video jobs
- normalized clips
- concat
- final

### Style bible
Invalidate:
- keyframes if style embedded
- prompts
- video jobs
- normalized clips
- concat
- final

### One shot prompt
Invalidate only:
- that shot's video job
- that shot's normalized clip
- final concat
- final render

### One shot video
Invalidate:
- normalized version of that shot
- final concat
- final render

### Narration/music/subtitles only
Do NOT regenerate AI video.
Invalidate:
- final render only

---

# 11. `run_manifest.json`

```json
{
  "project_id": "p_20261005_001",
  "schema_version": "1.0",
  "project_status": "GENERATING",
  "created_at": "2026-10-05T13:00:00Z",
  "updated_at": "2026-10-05T13:10:00Z",
  "shot_count": 6,
  "shots": {
    "shot_001": {
      "status": "NORMALIZED",
      "prompt_hash": "sha256:...",
      "keyframe_hash": "sha256:...",
      "video_hash": "sha256:..."
    },
    "shot_002": {
      "status": "RUNNING"
    }
  }
}
```

Write manifest atomically:
1. Write temp file.
2. fsync if needed.
3. Rename temp -> final.

---

# 12. Media Target Contract

Canonical output:
- Container: MP4
- Video: H.264
- Pixel format: yuv420p
- Resolution: 1080x1920
- FPS: 30
- Audio: AAC
- Audio sample rate: 48 kHz preferred

Tolerance:
- Per-shot duration: configurable.
- Final duration: configurable, e.g. max(0.5 s, 3% target).

---

# 13. FFprobe Validation Contract

Store per clip:

```json
{
  "shot_id": "shot_004",
  "valid": true,
  "duration_sec": 5.97,
  "width": 1080,
  "height": 1920,
  "fps": 30.0,
  "video_codec": "h264",
  "pixel_format": "yuv420p",
  "has_audio": true,
  "errors": []
}
```

Fail if:
- no video stream
- duration <= 0
- unreadable metadata
- corrupt file
- invalid dimensions
- unacceptable duration deviation

---

# 14. Provider Adapter Error Mapping

Normalize external errors:

```text
AUTH_ERROR
RATE_LIMIT
QUOTA_EXCEEDED
INVALID_INPUT
SAFETY_REFUSAL
PROVIDER_5XX
TIMEOUT
JOB_FAILED
DOWNLOAD_FAILED
CORRUPT_OUTPUT
UNKNOWN_PROVIDER_ERROR
```

This allows retry policy to remain provider-independent.
