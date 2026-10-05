# Multi-Shot Identity Director (M0 skeleton)

Produces the `character_bible` and `style_bible` artifacts — the immutable
identity and style locks shared by every shot prompt.

**Canonical artifacts:** `character_bible`, `style_bible`

## Workflow

1. Read the `story` artifact.
2. For each story character, write a character entry with a stable `char_*`
   id, a `locked_identity` (type + body/face/eyes/fur/markings/clothing),
   personality, motion_style, and forbidden_changes.
3. Write the `style_bible` with `visual_style`, lighting, camera/motion
   language, color, and non-empty `render_rules`.
4. Validate via `lib/multishot_schemas.validate_character_bible_cross_fields()`
   and `validate_style_bible_cross_fields()`.
5. Persist to `projects/<id>/planning/character_bible.json` and
   `style_bible.json`; gate on human approval.

## Quality Bar

- Every character has `locked_identity.type` (a shot prompt with no character
  lock is rejected downstream).
- Character ids are unique and stable across re-runs.
- Style `render_rules` is non-empty.
