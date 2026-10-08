# Multi-Shot Story Director (Beta, non-production-ready)

Produces the `story` artifact — the project narrative all later shots draw from (Beta status; no claim of end-to-end or quality release completed).

**Canonical artifact:** `story`

## Public Tool & Operational Binding
- **Tool operations:** Uses `multishot` tool with operations such as `prepare_shot`, `review`, `checkpoint`.
- **Creative vs Technical:** Python technical tools handle structure, validation, and storage; they do NOT make creative decisions.
- **Cost & Quota:** Cost tracking uses `actual_cost_source=estimate` (not real billing); failure/unknown cost reservations are retained.
- **Quality Gates:** Live provider and human quality gates are blocked pending explicit approval; stable cron is not activated.

## Workflow

1. Read the persisted `request` artifact.
2. Write a story with `title`, `topic`, `summary`, `beats` (≥3 covering hook, escalation, climax, and resolution/punchline), `characters` (≥1 main), `locations`, and optional `important_props`.
3. Validate via `lib/multishot_schemas.validate_story_cross_fields()`.
4. Persist to `projects/<id>/planning/story.json`; gate on human approval.

## Quality Bar

- Beats must cover hook, escalation, climax, and a closing beat (resolution or punchline).
- The story must decompose into ≥2 shots within the request's shot policy.
- Beta status maintained: no claim of production-ready completion.
