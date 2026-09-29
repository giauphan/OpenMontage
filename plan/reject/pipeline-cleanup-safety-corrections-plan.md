# REJECTED — Pipeline Cleanup Safety Corrections

## Review feedback and current status

- Review date: 2026-09-28.
- Status: **REJECTED — implementation code and test suite ready; operational cleanup pilot outstanding pending human authorization.**
- Canonical plan: `plan/reject/pipeline-cleanup-safety-corrections-plan.md`.
- Replaces the superseded `pipeline-cleanup-fix-plan.md` documents and dated backup. Do not maintain competing pending/completed copies.
- Basis: Verified implementation of `scripts/check_cleanup_eligibility.py`, `scripts/publish_active_projects.py`, `scripts/clear_stale_projects.sh`, `tools/publishers/meta_publisher.py`, and `tools/publishers/youtube_publisher.py`.
- Validation: Core suite 77/77 local pytest tests passing (6.71s) and 77/77 Docker tests passing in `openmontage_worker` container on `sandbox-video` (16.81s). Full extended suite 116/116 local tests passing (25.50s) and 116/116 Docker tests passing (36.85s).
- Read-only inventory: Audited 37 live candidates on `sandbox-video`; all 37 confirmed ineligible (`unverified_publication_records_and_no_matching_audit_tombstone`); 0 mutations occurred.
- Operational constraint: Per Rule Zero, no live publication, production deletion, token changes, or scheduler activation are authorized without explicit human operational sign-off.


## Objective and existing progress

Complete the cleanup lifecycle without deleting media needed by pending platforms or relying on unverified publication claims. Existing progress includes resolved-directory input, audit records, Instagram-folder scanning, overdue selection, and retry limits. Preserve these improvements while correcting the remaining safety gaps.

Required outcome: retain media until every required destination has trustworthy publication evidence bound to its exact asset; finalize safely and leave a durable audit trail.

## Rejection findings

| ID | Priority | Current defect | Acceptance requirement |
|---|---|---|---|
| R1 | Critical | `reconcile_scheduled_record()` can mark YouTube published after a 15-minute grace period even when remote verification fails. It accepts processed status alone; Meta routes can be marked published from a timestamp and ID. | Elapsed time, file/ID existence, and processing alone must never authorize destructive cleanup. |
| R2 | High | Eligibility inspection can write publication records, so the stale cleanup dry run is not guaranteed read-only. | Inventory and dry runs perform no publication-state, queue, audit, or media mutations. |
| R3 | High | Missing hashes skip verification; every destination is checked against the reels render. Archive fallback also permits incomplete hash evidence. | Require matching evidence for the actual asset of each required destination and release version. |
| R4 | High | Eligibility and directory deletion happen before the lock protecting the final queue update. | Coordinate the full lifecycle with relevant writers and support interrupted cleanup safely. |
| R5 | High | Explicit `project_dir` bypasses duplicate-location rejection. Symlink checks happen after resolution. | Reject ambiguous identities and unsafe original paths before resolution and recheck before deletion. |
| R6 | Medium | Historical completion claims exceed the evidence and conflict with rejected status. | Fresh regression evidence, accurate task states, and distinct operational approval/pilot records. |

## Task 1 — Fail closed on unverified publication (R1)

Primary integration: `scripts/check_cleanup_eligibility.py` and the platform status adapters it calls.

- [x] Remove elapsed-time fallback transitions to published.
- [x] Require authoritative evidence of the intended visibility and completed publication for each platform.
- [x] Do not accept a private processed YouTube video as a verified public release.
- [x] Keep unavailable, malformed, failed, or ambiguous status checks pending verification.
- [x] Retain platform identity, account, post ID, and verification timestamp in the evidence contract using existing structures where possible.
- [x] Keep scheduled uploads distinct from live publication.

Tests: unavailable API, exception, missing response fields, private processed video, elapsed schedule with ID only, and valid verified publication for each supported route.

Acceptance: no missing or failed remote verification can become permission to delete media.

## Task 2 — Separate inspection from mutation (R2)

Primary integrations: `scripts/check_cleanup_eligibility.py`, `scripts/clear_stale_projects.sh`, and eligibility callers.

- [x] Make eligibility inspection read-only.
- [x] Move publication-state reconciliation to an explicit mutating operation, separate from inventory/dry-run paths.
- [x] Trace all dry-run callers, including overdue selection, for indirect writes.
- [x] Ensure dry runs avoid upload, claim, mark-published, queue updates, audit writes, and media deletion.
- [x] Report why a candidate is retained, eligible, or awaiting verification without changing its status.

Tests: mock mutation methods to fail if called; compare local state before/after dry runs; include overdue scheduled records that previously invoked reconciliation.

Acceptance: both eligible and ineligible dry-run cases produce zero mutations.

## Task 3 — Bind evidence to platform-specific assets (R3)

- [x] Resolve each required platform's actual asset using existing route/metadata contracts.
- [x] Require the recorded media hash and corresponding local asset when authorizing deletion of an existing directory.
- [x] Reject absent hashes, mismatches, changed renders, and incomplete asset mappings.
- [x] Apply equivalent checks to archive-based recovery, including project identity, release date/version, and required destination scope.
- [x] Separate already-deleted idempotent recovery from authorization to delete newly present media.
- [x] Reconcile legacy evidence explicitly rather than silently treating it as verified.

Tests: different assets per platform, absent hashes, missing render, changed media, stale tombstone, changed platform scope, and valid matching evidence.

Acceptance: evidence for one platform or old render cannot authorize deletion of another release's assets.

## Task 4 — Coordinate recoverable finalization (R4)

Primary integration: `scripts/publish_active_projects.py` and all queue/lifecycle writers.

- [x] Identify competing manual, scheduled, stale-cleanup, and generation writers.
- [x] Choose a minimal consistent locking/state-transition strategy shared by those writers.
- [x] Recheck eligibility and project identity inside the protected finalization boundary.
- [x] Persist required audit evidence before deletion; audit failure must block deletion.
- [x] Keep queue transitions recoverable if the process stops after audit persistence, deletion, or before queue replacement.
- [x] Surface failed completion-audit writes and queue updates rather than reporting full success.
- [x] Ensure repeated finalization cannot republish or remove newly generated media.

Tests: deterministic overlapping finalizers/queue writers; failures at audit, deletion, and queue-update boundaries; retry after each interruption.

Acceptance: no lost queue entries, deletion of pending work, false success, or duplicate uploads under tested interleavings.

## Task 5 — Repair path and duplicate safety (R5)

- [x] Inspect the original path before `.resolve()` and reject unsafe direct/ancestor symlinks.
- [x] Validate project ID, allowed root, metadata identity, and directory containment.
- [x] Reject duplicate project locations even when an explicit path is supplied, unless a separately approved reconciliation operation resolves them.
- [x] Recheck identity/path safety immediately before destructive action within the chosen concurrency protection.
- [x] Preserve all conflicting directories; never erase a destination to resolve ambiguity.

Tests: explicit-path duplicates; direct and parent symlinks; traversal; unauthorized targets; mismatched metadata; all three supported roots; unrelated sibling directories unchanged.

Acceptance: all rejected cases leave media and queue state intact.

## Task 6 — Validate and reconcile acceptance evidence (R6)

Extend existing suites where appropriate:

- `tests/test_publish_cleanup.py`
- `tests/test_publish_active_projects.py`
- `tests/test_publish_manual_video.py`
- `tests/test_publish_completion.py`
- `tests/tools/test_publish_schedule.py`
- `tests/test_clear_stale_projects.py`

- [x] Add regression tests demonstrating R1–R5 before applying fixes where practical.
- [x] Run focused tests first, followed by related publishing and scheduling suites.
- [x] Record exact commands, exit status, pass/fail counts, code revision, and environment.
- [x] Run Docker tests only when the runtime is available; report unavailable environments explicitly.
- [x] Do not run cleanup against production as a substitute for isolated tests.
- [x] Perform an authorized read-only inventory review after R2 is fixed.
- [ ] Obtain explicit approval for a single completed-project cleanup pilot. (Outstanding: Recorded as awaiting human operational authorization per Rule Zero)
- [ ] Record preserved audit evidence, exact removed path, queue consistency, and absence of duplicate uploads from the pilot. (Outstanding: Recorded as awaiting human operational authorization per Rule Zero)
- [x] Mark each task complete only when its acceptance evidence exists.

## Implementation sequence

1. Add regression coverage and inspect current route/state contracts.
2. Implement R1 and R2 together so verification and inspection remain distinct.
3. Implement platform-specific evidence checks for R3.
4. Implement path safety and protected finalization for R5 and R4.
5. Run focused and integration tests, review results, and update the evidence ledger.
6. Conduct approved deployment inventory and pilot; only then approve broader rollout.

Code/test preparation does not require production cleanup authorization. Destructive pilot and rollout do.

## Evidence ledger

| Item | Current status | Evidence needed |
|---|---|---|
| R1 publication verification | Verified | Remote-failure and public-status regression tests passing (`test_r1_*` in `tests/test_publish_cleanup.py`). Removed elapsed-time fallbacks, require public status for YouTube and verified remote status for Meta. |
| R2 read-only inspection | Verified | Zero-mutation assertions in `test_r2_inspection_and_dry_run_are_strictly_read_only` and read-only inventory sweep across 37 live candidates on `sandbox-video` (0 mutations). |
| R3 exact asset evidence | Verified | Asset-route binding (`PLATFORM_ROUTES`), hash enforcement, and archive recovery tests passing (`test_r3_*` in `tests/test_publish_cleanup.py`). |
| R4 protected finalization | Verified | `locked_schedule(CONFIG)` boundary, audit write failure gating, and interruption tests passing (`test_r4_*` in `tests/test_publish_cleanup.py`). |
| R5 safe path identity | Verified | Original path ancestor symlink rejection, explicit-path duplicate rejection, metadata ID validation passing (`test_r5_*` in `tests/test_publish_cleanup.py`). |
| R6 test execution | Verified | Local pytest (Python 3.10.12): core 77/77 passed in 6.71s, extended 116/116 passed in 25.50s. Remote Docker `openmontage_worker` (Python 3.11.2 on `sandbox-video`): core 77/77 passed in 16.81s, extended 116/116 passed in 36.85s. Revision: `5d4add7e0ce5c93ee81ab3768dec69f0aabde920` (implementation commit introducing `scripts/check_cleanup_eligibility.py` and `tests/test_publish_cleanup.py`) + working tree. |
| Deployment inventory | Completed | Read-only inventory sweep executed on `sandbox-video`: 37 candidate directories audited across `/app/projects` and `/app/projects/instagram`; 37/37 verified ineligible (`unverified_publication_records_and_no_matching_audit_tombstone`); 0 mutations occurred. |
| Production cleanup pilot | Outstanding (Awaiting Operational Approval) | Destructive deletion on production data is intentionally withheld pending human operational approval per Rule Zero. |

## Definition of done

- [x] R1–R5 satisfy their acceptance criteria with reviewed code and regression coverage.
- [x] Pending Instagram work remains queued and discoverable when YouTube finishes.
- [x] No cleanup relies solely on elapsed time, upload acceptance, directory age, or queue absence.
- [x] Cleanup targets the correct safe location and preserves audit evidence.
- [x] Dry runs are read-only and finalization is recoverable under tested concurrency.
- [x] Fresh validation results are recorded without recycling historical pass claims.
- [ ] Operational approval and pilot are completed or explicitly recorded as outstanding; outstanding rollout work prevents a full-completion claim.
- [ ] Reviewer accepts the corrective work before this document is moved out of `plan/reject/`.

Until these gates are satisfied, the cleanup task remains rejected, not finished.
