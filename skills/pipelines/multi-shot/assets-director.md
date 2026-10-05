# Multi-Shot Assets Director (M0 skeleton)

Drives per-shot generation through the provider, tracking state in the run
manifest. Full job scheduling, recovery, and provider adapters arrive in M2;
M0 establishes the stage contract and the manifest update path.

**Canonical artifact:** `asset_manifest`

## Workflow

1. Read the approved `shot_plan` and `continuity_state`.
2. For each shot, build its prompt (M1) and submit a provider job (M2). M0
   records each shot as `RUNNING` in the run manifest via
   `lib/multishot_workspace.update_shot_status()`.
3. Persist the `asset_manifest` and update the run manifest atomically.
4. Gate on human approval before any paid generation.

## Quality Bar

- Concurrency is bounded (M2 default 2–3).
- Job state transitions are version-checked; no stale asset finalizes.
