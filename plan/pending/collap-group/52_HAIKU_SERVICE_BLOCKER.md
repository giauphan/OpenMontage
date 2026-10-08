# Resume state: Haiku service blocked

Plan INCOMPLETE. Base verified commit ee69a13 remains unchanged. New local uncommitted work: lib/multishot_generation.py, lib/multishot_session.py, tests/contracts/test_multishot_generation_preflight.py. Authored locally by claude-haiku-4-5-20251001. Source was copied to isolated remote checkout for validation only. Stable checkout untouched.

## Latest actual validation
Focused tests test_multishot_generation_preflight.py and test_multishot_prepare.py: 15 passed, 1 failed in 2.97s. Failure test_regenerate_clears_job_spec: old shot.job_spec survives regenerate_shot. The earlier full green suite applies to ee69a13, NOT these uncommitted changes.

## Immediate repair
Use local Haiku ONLY. Clear job_spec/job_input_hash whenever regeneration/reference invalidation clears bound_input, including downstream stale transitions; preserve prior spec/hash in history. Keep regression assertion. Replace handmade marker/directories in preflight fixture with real init_multishot_project. Then synchronize selected files to isolated server and rerun focused tests.

## Pending public finalization
Prompt 51_PUBLIC_FINALIZATION.md remains unfinished. No tools/video/multishot.py edits or test_multishot_public_finalize.py file were created by these attempts. Smaller next task: wire finalize and validate_completion plus fail-closed compose checkpoint, then assign real-media public tests separately.

## Concrete execution blocker
Initial two attempts failed with API 503, all targets skipped by pre-dispatch filters. Preflight retry succeeded; finalization retry timed out after hook evidence request. Latest bounded fix and finalization calls received repeated API 429 rate_limit events and timed out after 360/420 seconds without edits. These supervised invocations are stopped. No model substitution or hook disabling performed. Resume only after requested Haiku service capacity is available; use serial small tasks to reduce pressure.

Generation scheduler/CostTracker integration, end-to-end workflows, docs/evidence ledger and release review remain pending. No paid media generation, deployment or cron activation is authorized by this status file.
