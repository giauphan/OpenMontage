# Multi-Shot Compose Director (M0 skeleton)

The terminal stage. Produces the `render_report` and the final assembled
video.

**Canonical artifact:** `render_report`

## Runtime routing (HARD RULE)

`compose` routes through `video_compose`, which dispatches on
`edit_decisions.render_runtime`. Do NOT silently pick a runtime.

- multi-shot V1 assembles and masters with **FFmpeg** (ordered concat of the
  normalized shots, then optional narration/music/SFX/subtitle mux).
- If `render_runtime` was locked to `remotion` or `hyperframes` at proposal,
  `video_compose` routes to that engine instead. When only FFmpeg is
  configured, name `HyperFrames` and Remotion as the unavailable/deferred
  options and record `render_runtime_selection` in the `decision_log` with
  `rejected_because` — do not drop the record.
- A final video may only be published when every planned shot is accepted and
  validated; a missing or failed shot blocks finalization.

## Workflow

1. Read `edit_decisions` (ordered cut list from the shot plan).
2. `video_compose` routes on `render_runtime` and produces
   `renders/final_video.mp4`.
3. Write a schema-valid `render_report` and the `compose` checkpoint
   (human approval gate).

## Quality Bar

- Final duration within tolerance of the shot-plan target.
- Concatenation order matches the shot-plan order, not directory listing.
- `render_runtime` is recorded; no silent fallback.
