# 06 — Recovery Plan for Incomplete or Failed Implementation

## Start here

This is an implementation repair handoff, not authorization to run paid generation.
Read `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`, documents 01–04, and the current section
of document 05. Preserve existing useful code and unrelated work.

The initial pass produced useful helpers and 152 passing focused tests, but missed
integration and failure paths. Resume at the failed acceptance boundaries, not at
an empty scaffold. Original TASK 001–021 and all release gates remain in scope.

**Execution order:** R0 → R1 → R2/R3/R4 → R5 → R6. After R1 interfaces are agreed,
R2, R3 and R4 may proceed in parallel with disjoint file ownership. Integration
must wait for every required dependency. The agent still owns production policy;
Python tools must not become a second creative orchestrator.

## 1. Task failure protocol — mandatory for every recovery task

Use these statuses in document 05:

- `not_started`: no implementation attempt yet.
- `in_progress`: active work, no acceptance claim.
- `failed`: reproduced behavior violates a requirement.
- `reopened`: earlier completion claim disproved or missing required evidence.
- `implemented_unverified`: change exists but acceptance has not passed.
- `blocked`: cannot proceed because of a named unmet dependency or permission.
- `verified`: all exit checks for the stated scope ran and passed.

For each task:

1. Read the caller and acceptance criterion; create the smallest reproducible
   regression test. Confirm it fails for the expected reason before fixing.
   For absent functionality, record the missing behavior rather than a fabricated
   test result. Infrastructure failures are not product regression evidence.
2. Record task ID, expected/observed behavior, exact command/exit outcome,
   environment, code revision plus dirty-diff identity, and sanitized evidence.
3. Identify root cause. Make a narrow repair and preserve valid assets/attempts.
4. Run the reproduction, neighboring tests and the relevant integration gate.
   Move to `verified` only for the scope actually exercised.
5. If unsuccessful, keep the task `failed`/`reopened` and record what changed and
   why it failed. After two focused unsuccessful repair attempts, stop blind edits:
   perform a fresh review or delegate a bounded diagnosis, then record a revised
   approach. If unresolved, mark blocked with the exact next action/decision.
6. Block dependent tasks, not unrelated work. Continue independent offline work.
   Never suppress a test, weaken validation, replace real integration with a mock,
   or mark the whole milestone complete to get a green report.
7. If a verified task regresses, reopen it and invalidate dependent acceptance
   claims. Preserve earlier evidence labeled with its revision, not as current proof.

Failure categories and actions:

| Category | Required response |
|---|---|
| Code/contract failure | Reproduce, repair root cause, regression-test actual call path |
| Environment missing | Record dependency/version; use approved setup or mark affected gate blocked |
| Auth/quota/paid approval | No automatic retries or provider substitutions; finish offline work |
| Provider transient error | Bounded technical retries within approved policy; retain job/attempt identity |
| Unknown remote submission | Reconcile by durable intent/idempotency or escalate; never blindly resubmit |
| Visual quality/continuity | Reject acceptance, preserve artifacts, request approved revision; metadata pass is insufficient |
| Conflicting requirement | Record conflict and proposed resolution; ask only when repository rules cannot resolve it |

A session ending early is not success. Leave a restart note with current task,
last failing test, changes made, next exact action, dependencies and permissions.

## 2. Recovery tasks and exit gates

### R0 — Establish honest baseline and failure tests

Scope: audit evidence, all source requirements, no broad rewrite.

- Re-run the focused suite and record baseline/environment; preserve existing tests.
- Add regressions for checkpoint mismatch, missing/corrupt resume files, lost job
  handles, and subtitle burn execution. Add unsupported-case tests as defects emerge.
- Expand document 05 to one row for each TASK 001–021, each IT-01–06, E2E-01,
  performance/security checks and all ten release gates. Link each to a test or
  explicit blocker; untested coverage cannot inherit `verified` from a group row.
- Classify audit observations as reproduced, source-inspected, or unverified.

Exit: failures are independently reproducible and the coverage ledger has no
unsupported completion claims. This gate establishes defects; it does not fix them.
If baseline differs, investigate and update evidence rather than relying on old counts.

### R1 — Repair pipeline, artifact, workspace and tool integration

Inspect: `pipeline_defs/multi-shot.yaml`, `lib/checkpoint.py`,
`schemas/artifacts/`, `lib/multishot_workspace.py`, registry/tool conventions.

- Resolve `idea` producing `request` while canonical checkpoint policy requires
  `brief`. Prefer mapping supporting multishot records into existing canonical
  outputs; change shared contracts only compatibly with explicit tests.
- Ensure all custom artifacts are schema-validated at real persistence boundaries;
  unregistered artifact names must not silently bypass required validation.
- Initialize through the canonical project workspace contract and preserve project
  markers, checkpoint history, approvals, asset references and progress visibility.
- Expose multishot technical operations through real registry-discovered tools;
  no test-only helper route or invented tool names in director instructions.
- Exercise gates through public APIs, including rejection without human approval.

Exit: actual project init → checkpoint write → reload/validate succeeds for the
new workflow; invalid artifacts and missing approval fail; existing pipeline
contracts still pass. Tests that merely parse YAML do not satisfy this gate.
On failure: keep M0/M5 integration reopened and block R5.

### R2 — Implement real provider boundary and durable recovery

Inspect: `lib/multishot_jobs.py`, provider tools, persistence/job schemas.

- Submit a validated full payload: prompt, references, duration, provider/model,
  settings and revision/input hashes. A hash alone cannot render a shot.
- Integrate at least one existing real provider lifecycle adapter. Test its request,
  response/status/error mapping offline with a mocked transport. Credentials are
  needed for live execution, not for writing and contract-testing the adapter.
- Persist submission intent, idempotency key, handle, transitions and attempts
  atomically. Persist running handles before returning; survive process restart.
- Reconcile uncertain submission without another paid request. Poll known handles;
  retry interrupted downloads from the same completed job, not by regenerating.
- Validate resumed outputs against file existence, integrity, current hashes and
  validation reports. Missing/corrupt/stale assets cannot be marked completed.
- Bound remote jobs separately from threads/downloads; preserve order and deadlines.
  Apply continuity eligibility from R3 before dispatch. Keep URLs/secrets redacted.

Exit: fresh-process recovery tests kill/restart after intent, submission, handle
persistence and partial download; verify submission counts, cost-reservation reuse,
valid asset reuse and attempt history. 20 independent jobs respect concurrency 3.
Include 429/5xx/auth/safety/quota failures and uncertain-submit escalation.
On failure: retain successful jobs/assets, block affected downstream work, never
hide duplicate submission risk behind a manually supplied test handle.

### R3 — Finish director skills and continuity acceptance integration

Inspect: `skills/pipelines/multi-shot/`, prompt/reference/continuity helpers.

- Replace M0 skeleton prose with current, executable registry tool workflows for
  planning, reference creation, job submission/reconciliation, review and recovery.
- Put pre-spend approval before submission, not after a numbered submission step.
- Wire full prompts and reference provenance into actual provider payloads.
  Validate image readability, identity review outcome and shot/reference ownership.
- Persist immutable planned inputs separately from accepted state. Accept once,
  in dependency order; failed/rejected/stale shots never mutate accepted continuity.
- Regeneration creates revisions/history. Changed end state invalidates dependent
  later shots; same-state media replacement rebuilds only dependent media.
- Connect invalidation to the scheduler and finalization, not just returned lists.

Exit: persisted integration tests cover rejection, repeat acceptance, concurrent
completion, preserved retry inputs, changed/unchanged-state regeneration and every
invalidation rule from document 02. Skills no longer refer to completed features
as future work. Human visual review is recorded separately from technical checks.
On failure: mark dependent shots stale/blocked; no synthetic acceptance or silent
story/identity changes to force progression.

### R4 — Repair final media execution and fail-closed publication

Inspect: `lib/multishot_media.py`, `lib/multishot_final.py`, real media tests.

- Use video re-encoding when burning subtitles; stream-copy only when no video
  filtering is needed. Explicitly map streams and choose a compatible subtitle
  codec for muxing; do not assume FFmpeg default selection is correct.
- Implement actual configured ducking/loudness/fades, not an `amix` labeled ducking.
  Handle silent bases, source audio, narration, music, SFX and captions explicitly.
- Enforce requested output profile, bounded duration/timeouts and atomic publication.
- Prove concat order with distinct clip content/boundary frames, not duration alone.
- Completion checks must bind the current plan/revisions and fresh validation
  evidence to actual accepted media. An old final cannot validate a changed run.

Exit: execute FFmpeg on generated local fixtures for silent, narration-only,
multiple audio tracks, ducking, SFX, subtitle burn and mux, mixed source formats,
corrupt input and missing-middle-shot scenarios. Verify streams, decoded output,
burned caption presence, order, duration bounds and required audio behavior.
Mocked subprocess/argument tests alone are insufficient. Missing binaries block
media acceptance, not permission to mark it verified.

### R5 — Prove the offline workflow and complete operator handoff

Dependencies: R1–R4 verified.

- Execute IT-01–06 through the actual public tool/checkpoint path with a fake remote
  service producing valid distinct video fixtures, not `fake-video-bytes` files.
- Run two-shot and six-shot/30-second workflows, permanent middle-shot failure,
  fresh-process crash recovery, retry-one and regenerate-one variants.
- Verify current canonical artifacts, per-shot records, reports and final media
  link correctly; measure concurrency and verify no silent missing-shot completion.
- Run relevant existing regression suites; report unrelated baseline failures.
- Update `docs/multishot.md` with commands actually executed and their prerequisites,
  expected artifacts, error/resume instructions and provider lifecycle limits.
- Independently review the requirement-to-evidence ledger and close only fulfilled
  source tasks. Offline integration/performance tests belong here, not deferred to M6.

Exit: all offline-required source criteria individually pass with evidence.
Conclusion may say “offline implementation verified”; never “release-ready.”
On failure: reopen the responsible R task and its dependent acceptance gates;
keep useful passing evidence scoped to the tested revision.

### R6 — Execute approved real-provider release gates

Dependencies: R5, explicit provider/model/runtime/budget approval and credentials.

- Run real minimum-two-shot and six-shot Mochi scenarios from document 03.
- Verify visual identity, costume, setting, persistent mess/damage and story order
  with explicit review evidence. Demonstrate resume and single-shot regeneration.
- Record ffprobe/decode validation, output paths, cost and all ten release gates.
- If quality fails, return to the relevant planning/reference/job/media task; do
  not substitute a provider, static slideshow or unrelated clip without approval.

Exit: every mandatory release gate passes. Otherwise remain not release-ready,
with exact blockers and next actions. No indefinite paid retry loops.

## 3. Evidence record template

For every recovery task and source requirement, keep this in document 05:

```text
Requirement / recovery ID:
Status and dependency:
Expected behavior:
Observed failure / root cause:
Code revision and working-diff identity:
Environment / dependency versions:
Regression command, exit code and sanitized log path:
Repair attempts and changed paths:
Integration command, exit code and output evidence:
Skipped checks and why:
Reviewer / review findings:
Remaining blocker and exact next action:
```

Do not store credentials or signed URLs in evidence. Preserve original reports
as history. Update current summaries so they cannot contradict unresolved rows.

## 4. Prompt for the next implementation agent

> Read AGENT_GUIDE.md, PROJECT_CONTEXT.md and documents 01–06 in
> plan/pending/collap-group/. The initial implementation is incomplete despite
> passing helper tests. Follow 06_RECOVERY_PLAN.md, beginning with R0 and R1.
> Repair existing code rather than rebuild it. Reproduce each failure, implement
> the narrow fix, and verify the actual public/persisted workflow. Continue through
> unblocked offline recovery tasks; follow the failure protocol after unsuccessful
> attempts. Update the current ledger in 05_IMPLEMENTATION_STATUS.md with exact
> evidence and a resumable next action. No paid calls, commits, weakened tests,
> invented successful runs or release-ready claims while required gates remain open.
