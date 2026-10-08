# Multi-Shot Idea Director (Beta, non-production-ready)

The planning stage of the multi-shot pipeline (Beta status; no claim of end-to-end or quality release completed). It produces the `request` and `story` artifacts and — per the repository's runtime-presentation governance contract — must surface the composition-runtime choice to the user before it is locked.

**Canonical artifact:** `request` (and `story`)

## Public Tool & Operational Binding
- **Tool operations:** Uses `multishot` tool with operations such as `init`, `status`, `prepare_shot`, `review`, `checkpoint`.
- **Creative vs Technical:** Python technical tools (`multishot`, schema validation, workspace initialization) handle orchestration and validation; they do NOT make creative decisions.
- **Cost & Quota:** Cost tracking uses `actual_cost_source=estimate` (not real billing); failure/unknown cost reservations are retained.
- **Quality Gates:** Live provider and human quality gates are blocked pending explicit approval; stable cron is not activated.

## Runtime selection (HARD RULE)

This pipeline's `compose` stage routes through `video_compose`, which dispatches on `edit_decisions.render_runtime`. Even though multi-shot V1 assembles with FFmpeg, the agent MUST not silently default a runtime. Before locking `render_runtime` at proposal time:

- **Present both** available composition runtimes (Remotion and HyperFrames) plus the FFmpeg path that multi-shot assembly uses.
- Name `hyperframes` explicitly. If it is unavailable on this machine, say so and record `render_runtime_selection` in the `decision_log` with `rejected_because: "runtime not available on this machine"`.
- Log the full shortlist as `options_considered` under the `render_runtime_selection` decision category.

A decision-log entry that considers only one runtime when two are available is a CRITICAL reviewer finding.

## Workflow

1. Collect the user's topic and target duration (default 30s).
2. Build the `request` dict matching `schemas/multishot/request.schema.json` (default aspect "9:16", resolution 1080x1920, fps 30, shot_policy min_shots 2 / max_shots 8).
3. Validate via `lib/multishot_schemas.validate_request_cross_fields()`.
4. Persist to `projects/<id>/planning/request.json`.
5. Write the `request` checkpoint via tool/session checkpointing; proceed to the `story` stage.

## Quality Bar

- No NaN or Infinity values in resolution or fps.
- `shot_policy.min_shots` must be >= 2 and `max_shots` >= `min_shots`.
- The runtime choice is a conversation with the user, never a silent default.
- Beta status maintained: no claim of production-ready completion.
