---
name: pipeline-audit
description: Audit what the mod layer changed or blocked during a run
---

# Pipeline Audit

Use this skill when the user asks **"what did the mods do?"**, or wants a
post-run review of interceptions.

## What to inspect

- `mod.recentIntercepts()` — every interception with per-mod votes.
- `mod.listPanels()` — each mod's live panel: metrics, events, remembered entries.
- The pipeline timeline: `enter` / `exit` / `modified` / `blocked` / `asked` events.

## Report format

1. **Blocked** — tool calls that never ran, with the mod's reason.
2. **Modified** — before/after of the input that was rewritten.
3. **Asked** — calls that were handed to the user, and how the user answered.
4. **Allowed** — counts only; do not list every pass-through.

End with a one-line verdict on whether the run stayed within safe boundaries.
