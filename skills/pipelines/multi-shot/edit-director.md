# Multi-Shot Edit Director (M0 skeleton)

Builds the ordered `edit_decisions` cut list from the accepted shots.

**Canonical artifact:** `edit_decisions`

## Workflow

1. Read the validated shots (normalized in M3) and the `shot_plan` order.
2. Build a cut list that concatenates accepted, current, validated shots in
   plan order. Reject missing, extra, duplicate, or stale entries — hard
   cuts are the default.
3. Carry `render_runtime` through unchanged from the proposal lock.
4. Persist the `edit_decisions` artifact; gate on human approval.

## Quality Bar

- Concatenation order comes from the shot plan, never from directory listing.
- A missing or stale shot blocks finalization.
