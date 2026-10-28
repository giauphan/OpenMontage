---
name: flow-explainer
description: Explain how a request travels through the prompt → model → mod → tool call → screen pipeline
---

# Flow Explainer

Use this skill when the user asks **how a request is executed**, or wants to understand
what happens between their prompt and the answer on screen.

## The pipeline

1. **prompt** — the user's message enters the run.
2. **model** — the model reasons and decides whether it needs a tool.
3. **mod** — every tool call passes through the mod layer first. A mod may:
   - `allow` — let it through unchanged
   - `modify` — change the input, then let it through (e.g. `git push --force` → `--force-with-lease`)
   - `deny` — block it; the tool never runs
   - `ask` — hand the decision to the user
4. **tool call** — the (possibly rewritten) call is executed.
5. **screen** — the result comes back and is rendered.

## Mods vs hooks

- A **hook** is one-shot: it fires on an event and exits (`1x`).
- A **mod** stays running for the whole session, so it can remember things,
  keep a live panel, act as a guard, and accumulate metrics.

## How to answer

Walk the stages in order, and say explicitly which stage the current question is about.
When a mod changed or blocked something, quote the mod's reason verbatim.
