# Multi-Shot Planning Director (M0 skeleton)

Initializes the project workspace and the run manifest after the shot plan is
approved.

**Canonical artifact:** `continuity_state`

## Workflow

1. Read the approved `shot_plan`.
2. Initialize the workspace via
   `lib/multishot_workspace.init_multishot_project(project_id, title,
   pipeline_dir=...)` (idempotent; preserves existing work).
3. Initialize continuity state (version 1, `accepted_through_shot` null, empty
   state maps) and validate with
   `lib/multishot_schemas.validate_continuity_state_cross_fields()`.
4. Create the run manifest via
   `lib/multishot_workspace.init_run_manifest(project_dir, shot_count)` and
   persist atomically.
5. Write the `planning` checkpoint; gate on human approval.

## Quality Bar

- All planning artifacts are written under `projects/<id>/planning/`.
- The run manifest reflects the shot count and starts in `CREATED`.
