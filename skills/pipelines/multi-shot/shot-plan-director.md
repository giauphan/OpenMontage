# Multi-Shot Shot-Plan Director (M0 skeleton)

Produces the `shot_plan` artifact — the ordered, validated shot list.

**Canonical artifact:** `shot_plan`

## Workflow

1. Read `character_bible`, `style_bible`, and the `story` beats.
2. Decompose the story into shots, one dominant action each. Assign stable
   `shot_XXX` ids and contiguous `order` values 1..N (N >= 2).
3. Give every shot a `start_state`, `end_state`, `action`, `location`,
   `characters` (FK to `char_*` ids), `props`, and `transition_out`.
4. Validate via `lib/multishot_schemas.validate_shot_plan_cross_fields(plan,
   character_bible, request)`.
5. Persist to `projects/<id>/planning/shot_plan.json`; gate on human approval.

## Quality Bar

- At least 2 shots; unique ids; contiguous orders; each shot has a start and
  end state.
- Character references resolve to the character bible.
- Shot count stays within the request's `shot_policy` range.
