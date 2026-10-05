# Multi-Shot Story Director (M0 skeleton)

Produces the `story` artifact — the project narrative all later shots draw
from.

**Canonical artifact:** `story`

## Workflow

1. Read the persisted `request` artifact.
2. Write a story with `title`, `topic`, `summary`, `beats` (≥3 covering hook,
   escalation, climax, and resolution/punchline), `characters` (≥1 main),
   `locations`, and optional `important_props`.
3. Validate via `lib/multishot_schemas.validate_story_cross_fields()`.
4. Persist to `projects/<id>/planning/story.json`; gate on human approval.

## Quality Bar

- Beats must cover hook, escalation, climax, and a closing beat
  (resolution or punchline).
- The story must decompose into ≥2 shots within the request's shot policy.
