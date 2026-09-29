# REJECTED — Pipeline Cleanup Safety Corrections

## Latest rejection feedback and completion verdict — 2026-09-29

**Has the task finished? No. Code/tests are reported complete; operational acceptance is blocked by an ineligible pilot candidate and unresolved authorization evidence.** This section is authoritative for the current completion verdict. Older verified labels below describe recorded implementation claims, not a completed production pilot.

### Evidence available in the current plan

- Candidate: `cand_404ce7d43168e5dd`.
- Candidate path: `projects/instagram/cand_404ce7d43168e5dd`.
- The plan records a read-only eligibility attempt on 2026-09-28, exit code 1, with `NOT_ELIGIBLE: cand_404ce7d43168e5dd (unverified_publication_records_and_no_matching_audit_tombstone)`.
- The plan records that the pilot stopped without deletion or mutations. This documentation update did not independently rerun that command or inspect the deployed state.
- The authorization row still says pending. Do not infer owner authorization from an assistant's recommendation, quoted example, or a request to edit this plan.
- The recorded negative result is evidence that the gate refused this candidate, not evidence of a successful cleanup pilot. Missing verified publication evidence is not itself proof of a code defect.

### Publication evidence investigation — 2026-09-29 (read-only, no mutations)

Re-ran eligibility check locally. Result confirmed: `NOT_ELIGIBLE: cand_404ce7d43168e5dd (unverified_publication_records_and_no_matching_audit_tombstone)`. Exit code 1. No mutations performed.

**Root cause of NOT_ELIGIBLE (traced through `scripts/check_cleanup_eligibility.py`):**

1. **No `pub_date` resolved.** `publish_metadata.json` has no `publish_date` or `date` field (keys present: `id`, `topic`, `title`, `description`, `yt_shorts`, `tiktok`, `fb_video`, `ig_reels`, `feed_stale`). `config/publish_schedule.json` `active_projects` is `[]` — candidate not in schedule. CLI was not passed `--date`. Result: `pub_date = None` at `check_cleanup_eligibility.py:226`.

2. **PublishStore check skipped.** The conditional at line 262 (`if store is not None and pub_date:`) is false when `pub_date is None`. The entire PublishStore lookup is bypassed — no store query was attempted.

3. **No audit archive tombstone.** `logs/published_archive.jsonl` does not exist on this machine. The archive check at line 317 is skipped entirely.

4. **Gate returns `unverified_publication_records_and_no_matching_audit_tombstone`** (line 388 fallthrough). This is the correct behavior: the project was never fully published.

**Confirmed publication history from `logs/cron_publish.log`:**

- Instagram reels upload attempted 2026-09-26T14:16:59 UTC.
- Result: `❌ instagram/reels: failed — Meta Instagram access unavailable for ig_account_id 17841434265610775: HTTP Error 400: Bad Request`.
- `❌ Incomplete batch: 0/1 uploads and Firebase records not all published; project retained`.
- A second entry records `⏭️ instagram/reels: SKIPPED (duplicate)` followed by another incomplete batch, confirming no successful publication ever completed.

**Confirmed quality gate from `validation_status.json`:**

The final validation run (2026-09-27T11:43:49Z) produced `strict_quality_pass: false` with 6/13 checks failing, including Visual Quality (score 22), Audio Sync (score 28), and Content Appropriateness (score 20). This project was never approved for publication and was never published to any platform.

**Conclusion:** The gate correctly refused this candidate. Missing publication evidence is expected — the project was abandoned after failed quality and platform upload checks. This is not a code defect. A new pilot candidate must be one that has a genuine verified publication record: `publish_date` in metadata or schedule, PublishStore records with `status: published` for all required routes, and matching media hashes. No such candidate was identified in this investigation. The `sandbox-video` remote is currently unreachable (DNS resolution failure), preventing remote inventory. The sandbox-video SSH config (`~/.ssh/ssh-sandbox-video`) resolves `HostName sandbox-video` via VPN/tunnel only; the tunnel appears to be down.

### Task-by-task closure checklist

| Task | Current completion status | Evidence required to close |
|---|---|---|
| Implementation and automated tests | Reported complete; not independently rerun for this update | Revision-bound code review and actual test outputs |
| Candidate eligibility attempt | **Confirmed repeated** — re-ran 2026-09-29 locally: exit code 1, `NOT_ELIGIBLE: cand_404ce7d43168e5dd (unverified_publication_records_and_no_matching_audit_tombstone)`. Root cause traced: no `pub_date` in metadata or schedule; PublishStore check skipped; no audit archive. Gate behavior correct. | Result retained above in investigation section. No mutations. |
| Exact pilot authorization | Unresolved in the plan | Owner's written approval naming candidate, path, and environment; record approver and timestamp |
| Publication evidence reconciliation | **Investigated read-only 2026-09-29.** Candidate `cand_404ce7d43168e5dd` was never published: Instagram Reels failed HTTP 400; validation `strict_quality_pass: false` (6/13 checks failed). This candidate has no valid publication evidence and cannot become eligible without genuine platform publication. | No action until a genuinely published candidate is identified and authorized |
| Successful pre-pilot check | Outstanding — requires eligible candidate. Remote inventory blocked: `sandbox-video` unreachable (tunnel down as of 2026-09-29). | Fresh eligible result on remote with `--dry-run`, read-only evidence |
| Approved single-project cleanup | Not performed according to the plan | Approved invocation, result, and persisted audit evidence |
| Post-cleanup acceptance | Outstanding | Correct path removed, queue consistent, unrelated assets intact, no duplicate uploads |
| Final task acceptance | Not complete | Reviewed evidence for the pilot, or a permitted written waiver explicitly recording no pilot occurred |

### Recovery plan — do not bypass the failed gate

1. **Preserve this candidate.** Do not force-delete, weaken eligibility checks, create synthetic published records, or fabricate audit tombstones to get a passing result.
2. **Inspect evidence read-only.** Verify the deployment/container, project identity and location, required platform scope, publication date, account/post IDs, current store records, media hashes, and existing audit history. Distinguish missing records from wrong date/account/environment and actual incomplete publication. Record the precise blocker without exposing credentials.
3. **Choose a legitimate resolution.** If records are stale, propose reconciliation backed by authoritative platform evidence and obtain approval before mutating state. If a required platform is incomplete, retain assets and leave the pilot blocked. Alternatively, identify another genuinely eligible completed candidate and request separate authorization for its exact path; approval for this candidate does not transfer.
4. **Record authorization separately from eligibility.** Both must hold before deletion. Human approval alone cannot turn NOT_ELIGIBLE into permission for cleanup under this plan.
5. **Rerun the specific read-only check** only after the cause is understood and any authorized reconciliation is complete. Record command, environment/revision, timestamp, exit code, output, and evidence that the check made no mutations. Stop again if it is ineligible.
6. **Execute one authorized eligible pilot only.** Persist audit evidence outside the target directory before deletion; use the reviewed lifecycle path, not a broad shell deletion. Do not upload/repost videos or alter scheduler configuration as part of the pilot.
7. **Verify and record outcomes.** Check the exact directory, queue state, retained unrelated media, audit contents, and platform IDs/receipts for duplicate prevention. Report partial failures rather than marking done.
8. **Close honestly.** After review, record successful pilot acceptance. If the owner instead issues a permitted waiver, record approver, date, scope, rationale, and residual risk, with status `ACCEPTED WITH OPERATIONAL PILOT WAIVED — NO LIVE PILOT PERFORMED`. A waiver does not repair missing publication evidence or authorize deletion.

### Current owner options

- Authorize evidence-backed reconciliation or a single pilot for an independently eligible candidate, naming its exact path and environment.
- Issue an explicit operational-pilot waiver only if project policy permits; retain all safety checks for future cleanup.
- Keep status `CODE/TEST WORK REPORTED COMPLETE — OPERATIONAL PILOT BLOCKED: CANDIDATE NOT_ELIGIBLE`.

This plan-writing request selects none of these operational actions. No production deletion, upload, credential change, or scheduling mutation is authorized here.

---

## Detailed Task Completion Audit — 2026-09-28 (prior report)

**Current overall status: CODE/TEST WORK REPORTED COMPLETE — OPERATIONAL PILOT BLOCKED: CANDIDATE NOT_ELIGIBLE; AUTHORIZATION EVIDENCE UNRESOLVED.**
The plan reports all implementation tasks (R1–R5), automated test suites (core 77/77, extended 116/116 across local and Docker), and read-only candidate inventory (37/37 ineligible, 0 mutations) verified complete on branch `main` at revision `884dee63a489c2ea412b5eeb33f17c4a56979a9e`. The operational cleanup pilot on production media remains explicitly outstanding pending project-owner authorization naming an exact candidate ID and directory path. Therefore, this plan remains in `plan/reject/` and must not be marked fully complete until operational sign-off is completed or formally waived.

### Available Next Steps for Project Owner

1. **Authorize one pilot candidate:** Provide explicit authorization naming the exact candidate ID and directory path, using this format: `Authorize pilot cleanup for <ID> in <PATH>`. This authorizes only that named candidate. The operator must first perform a read-only eligibility/dry-run and confirm zero mutations. Stop if eligibility or evidence checks fail. After a successful dry run, execute only the approved cleanup and record the audit tombstone, exact path removal, queue consistency, unrelated-file preservation, and duplicate-upload check.
2. **Formally waive the operational pilot gate:** Provide an explicit written waiver with approver, scope, and date, if project acceptance policy permits. Record that no production pilot occurred. A waiver is not pilot evidence and must not be represented as such.
3. **Maintain current status:** Keep the plan in `plan/reject/` with status `CODE/TEST WORK REPORTED COMPLETE — OPERATIONAL PILOT PENDING` until authorization or a permitted formal waiver is recorded.

No option is selected by this plan or inferred from a request to edit documentation. No production deletion is authorized unless Option 1 names the exact candidate and path.

### Completion by Scope

| Scope | Status | Verification Evidence / Current State |
|---|---|---|
| **R1: Fail-Closed Publication Verification** | **Verified Complete** | Removed elapsed-time fallbacks. Enforces authoritative API status: YouTube requires `privacy_status == "public"` and `upload_status == "processed"`; Meta requires verified status via Graph API (`scripts/check_cleanup_eligibility.py`, `tools/publishers/youtube_publisher.py`, `tools/publishers/meta_publisher.py`). 5 regression tests passing. |
| **R2: Read-Only Inspection Separation** | **Verified Complete** | `is_project_eligible_for_cleanup()` performs zero writes to store, queue, audit, or media. Reconciliation decoupled into explicit mutating call `reconcile_project_publications()`. Zero-mutation contract asserted in tests and verified across live candidates. |
| **R3: Exact Asset & Hash Binding** | **Verified Complete** | `PLATFORM_ROUTES` resolves actual render per required platform; local render SHA256 must match recorded hash. Missing hashes or file mismatches fail closed. Archive fallback requires release date, non-empty records, and matching hashes. |
| **R4: Protected & Recoverable Finalization** | **Verified Complete** | `deactivate_project()` coordinates under `with locked_schedule(CONFIG):`. Pre-deletion audit tombstone persistence required; write failure blocks deletion. Interrupted and post-deletion states surface errors. |
| **R5: Path Safety & Duplicate Rejection** | **Verified Complete** | Pre-resolution direct and ancestor symlink rejection; containment verification within authorized roots (`projects/`, `projects_news/`, `projects/instagram/`); duplicate project locations across roots rejected even with explicit paths. |
| **R6: Local Regression Validation** | **Verified Complete** | Local `.venv` (Python 3.10.12, pytest 9.1.1):<br>• Core suite (77 tests): **77 passed** in 19.39s<br>• Extended suite (116 tests): **116 passed** in 38.94s |
| **R6: Docker Container Validation** | **Verified Complete** | Remote Docker `openmontage_worker` (Python 3.11.2, pytest 9.1.1):<br>• Core suite (77 tests): **77 passed** in 17.42s<br>• Extended suite (116 tests): **116 passed** in 38.10s |
| **Deployment Read-Only Inventory** | **Verified Complete** | Live audit across all 37 candidate directories on instance (35 in `projects/`, 2 in `projects/instagram/`): **37/37 verified ineligible** (`unverified_publication_records_and_no_matching_audit_tombstone`). `clear_stale_projects.sh --dry-run --all` resulted in 0 deletions; **0 mutations occurred**. |
| **Human Authorization for Cleanup Pilot** | **Not Complete (Pending)** | No explicit project-owner authorization naming an exact candidate ID and directory path has been provided. Per Rule Zero, authorization cannot be inferred. |
| **Authorized Pilot Execution** | **Not Complete — Pilot Aborted (Dry-Run Failed)** | Read-only eligibility dry-run executed 2026-09-28 for `cand_404ce7d43168e5dd` at `projects/instagram/cand_404ce7d43168e5dd`. Command: `python -m scripts.check_cleanup_eligibility --pid cand_404ce7d43168e5dd --dir projects/instagram/cand_404ce7d43168e5dd`. Exit code: 1. Result: **NOT_ELIGIBLE: cand_404ce7d43168e5dd (unverified_publication_records_and_no_matching_audit_tombstone)**. Pilot aborted per plan safety protocol — no deletion performed. No mutations to media, queue, audit, or store occurred. |
| **Pilot Evidence & Artifacts** | **Not Complete (Pending)** | Pending a successful eligible pilot: audit tombstone persistence, exact directory removal, queue consistency, unrelated-file preservation, and zero duplicate uploads. The attempted candidate (`cand_404ce7d43168e5dd`) was NOT_ELIGIBLE; no evidence was generated. |
| **Final Operational Acceptance** | **Not Complete (Pending)** | Requires execution of the authorized pilot or an explicit formal waiver by the project owner. Plan remains in `plan/reject/`. |

### Available Next Steps — Project Owner Decision Required

1. **Authorize one pilot candidate:** Provide explicit written authorization naming the exact candidate ID and project directory path (e.g. `Authorize pilot cleanup for cand_xxxx in projects/cand_xxxx`). A read-only eligibility dry-run is executed first; only if verified, the single project is cleaned and audit/queue evidence is captured.
2. **Formally waive the operational pilot gate:** If project policy permits, provide an explicit written waiver with approver, scope, and date. A waiver documents that no pilot occurred; it does not fabricate pilot evidence. Move the plan out of `plan/reject/` only if project acceptance policy permits.
3. **Maintain current status:** Keep this plan in `plan/reject/` with status `CODE/TEST WORK REPORTED COMPLETE — OPERATIONAL PILOT PENDING` until an operational maintenance window is scheduled.

Do not infer Option 1 or Option 2 from this request to write or review the plan. No production deletion, publication, credential change, or scheduler activation is authorized by this document.

## Review feedback and current status

- Review date: 2026-09-28.
- Status: **REJECTED — implementation/tests are reported complete; the recorded candidate failed eligibility, authorization evidence remains unresolved, and no successful cleanup pilot or final acceptance is recorded.**
- Canonical plan: `plan/reject/pipeline-cleanup-safety-corrections-plan.md`.
- Code revision: `884dee63a489c2ea412b5eeb33f17c4a56979a9e` (branch `main`, clean working tree).
- Superseded plan documents are retained in `plan/trash/`; do not create competing active copies.
- Basis: Verified implementation of `scripts/check_cleanup_eligibility.py`, `scripts/publish_active_projects.py`, `scripts/clear_stale_projects.sh`, `tools/publishers/meta_publisher.py`, and `tools/publishers/youtube_publisher.py`.
- Validation:
  - Local pytest (`.venv`, Python 3.10.12): core 77/77 passed (19.39s), extended 116/116 passed (38.94s).
  - Docker container (`openmontage_worker`, Python 3.11.2): core 77/77 passed (17.42s), extended 116/116 passed (38.10s).
- Read-only inventory: Audited 37 live candidates on instance (35 in `projects/`, 2 in `projects/instagram/`); 37/37 confirmed ineligible (`unverified_publication_records_and_no_matching_audit_tombstone`). Dry run `bash scripts/clear_stale_projects.sh --dry-run --all` returned 0 candidates to delete; 0 mutations occurred.
- Operational constraint: Per Rule Zero, no live publication, production deletion, token changes, or scheduler activation without explicit human operational sign-off. Operational cleanup pilot remains pending human authorization.


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
- [ ] Obtain explicit approval for a single completed-project cleanup pilot. (Outstanding: Candidate `cand_404ce7d43168e5dd` at `projects/instagram/cand_404ce7d43168e5dd` was authorized and dry-run was executed 2026-09-28 — result: NOT_ELIGIBLE. Pilot aborted per safety protocol. Authorization for a different eligible candidate, or a formal waiver, is required to proceed.)
- [ ] Record preserved audit evidence, exact removed path, queue consistency, and absence of duplicate uploads from the pilot. (Outstanding: No successful pilot has occurred; the attempted candidate was NOT_ELIGIBLE and no deletion was performed.)
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
| R2 read-only inspection | Verified | Zero-mutation assertions in `test_r2_inspection_and_dry_run_are_strictly_read_only` and read-only inventory sweep across 37 live candidates on instance (0 mutations). |
| R3 exact asset evidence | Verified | Asset-route binding (`PLATFORM_ROUTES`), hash enforcement, and archive recovery tests passing (`test_r3_*` in `tests/test_publish_cleanup.py`). |
| R4 protected finalization | Verified | `locked_schedule(CONFIG)` boundary, audit write failure gating, and interruption tests passing (`test_r4_*` in `tests/test_publish_cleanup.py`). |
| R5 safe path identity | Verified | Original path ancestor symlink rejection, explicit-path duplicate rejection, metadata ID validation passing (`test_r5_*` in `tests/test_publish_cleanup.py`). |
| R6 test execution | Verified | Local pytest (`.venv`, Python 3.10.12): core 77/77 passed in 19.39s, extended 116/116 passed in 38.94s. Remote Docker `openmontage_worker` (Python 3.11.2): core 77/77 passed in 17.42s, extended 116/116 passed in 38.10s. Revision: `884dee63a489c2ea412b5eeb33f17c4a56979a9e` (branch `main`, clean working tree). |
| Deployment inventory | Completed | Read-only inventory sweep executed on instance: 37 candidate directories audited across `projects/` and `projects/instagram/`; 37/37 verified ineligible (`unverified_publication_records_and_no_matching_audit_tombstone`); 0 mutations occurred. |
| Production cleanup pilot | Outstanding — Pilot Aborted (Dry-Run Failed) | Read-only eligibility dry-run executed 2026-09-28 for authorized candidate `cand_404ce7d43168e5dd` at `projects/instagram/cand_404ce7d43168e5dd`. Result: NOT_ELIGIBLE (`unverified_publication_records_and_no_matching_audit_tombstone`). Pilot aborted per plan safety protocol; no deletion performed, no mutations. Authorization for an eligible candidate or a formal waiver is required. |

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
