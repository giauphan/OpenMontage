---
name: mod-recipe
description: Write a new mod that intercepts tool calls between the model and the tool
---

# Mod Recipe

Use this skill when the user wants to **add a new mod** to the pipeline.

## Where mods live

`server/mods/builtin/` — one file per mod, each exporting a `createXxx(): Mod` factory.
Register the factory in `BUILTIN_FACTORIES` inside `server/mods/registry.ts`.

## The shape of a mod

```ts
export function createMyMod(): Mod {
  return {
    id: 'my-mod',
    name: 'My Mod',
    description: 'one line',
    capabilities: { memory, livePanel, asksFirst, guard, gauge },
    matchers: ['Bash'],           // omit to see every tool

    onSessionStart({ memory }) {},  // runs once, mod then stays alive
    onToolCall(ctx) {               // the interception point
      return { decision: 'modify', reason: '...', updatedInput: { ...ctx.input } };
    },
    onToolResult(ctx) {},
    panel() { return { title: 'My Mod', metrics: [], events: [] }; },
  };
}
```

## Return values of `onToolCall`

Returning `null` means "no opinion, let it through". The registry takes the
strictest verdict across all mods: `deny` > `ask` > `modify` > `allow`.

## Rules

- Keep the decision fast — it blocks the tool call.
- Always set a human-readable `reason`; it is shown in the pipeline UI.
- Prefer `modify` over `deny` when a safer variant of the command exists.
