# Multi-Shot Identity Director (Beta, non-production-ready)

Produces the `character_bible` and `style_bible` artifacts — the immutable identity and style locks shared by every shot prompt (Beta status; no claim of end-to-end or quality release completed).

**Canonical artifacts:** `character_bible`, `style_bible`

## Public Tool & Operational Binding
- **Tool operations:** Uses `multishot` tool with operations such as `prepare_shot`, `review`, `checkpoint`.
- **Creative vs Technical:** Python technical tools validate schemas and persistence; they do NOT make creative decisions.
- **Cost & Quota:** Cost tracking uses `actual_cost_source=estimate` (not real billing); failure/unknown cost reservations are retained.
- **Quality Gates:** Live provider and human quality gates are blocked pending explicit approval; stable cron is not activated.

## Workflow

1. Read the `story` artifact.
2. For each story character, write a character entry with a stable `char_*` id, a `locked_identity` (type + body/face/eyes/fur/markings/clothing), personality, motion_style, and forbidden_changes.
3. Write the `style_bible` with `visual_style`, lighting, camera/motion language, color, and non-empty `render_rules`.
4. Validate via `lib/multishot_schemas.validate_character_bible_cross_fields()` and `validate_style_bible_cross_fields()`.
5. Persist to `projects/<id>/planning/character_bible.json` and `style_bible.json`; gate on human approval.

## Quality Bar

- Every character has `locked_identity.type` (a shot prompt with no character lock is rejected downstream).
- Character ids are unique and stable across re-runs.
- Style `render_rules` is non-empty.
- Beta status maintained: no claim of production-ready completion.
