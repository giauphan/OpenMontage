# Haiku 4.5 — Medium-sized recovery tasks

## Execution policy

- Coding model: `claude-haiku-4-5-20251001` only. No fallback or other coding model.
- Supervisor prepares prompts, launches Claude, inspects diffs and runs validation;
  Claude makes application-code changes.
- Run one task per invocation with a **30-minute maximum**, not a five-minute
  deadline for the entire plan. This is a limit, not a promise of completion.
- At approximately 25 minutes, stop adding scope, validate and save a handoff.
  A 15-minute invocation suits a small follow-up. A 60-minute invocation is reserved
  for a separately approved integration task with demonstrated progress.
- Save streamed CLI output and a per-task report. Record session ID when available.
- If authentication/model/network fails, report that immediately; more time does
  not fix missing access. Do not switch models or mark the task complete.
- Read AGENT_GUIDE.md and PROJECT_CONTEXT.md. Document 06 supplies recovery policy;
  documents 01–04 retain acceptance requirements. Preserve unrelated existing work.
- No commits, branch changes, paid generation, secret inspection, or weakened tests.
- Passing helper tests does not establish full pipeline or release completion.

## Tasks and dependency order

| Task | Scope | Time limit | Exit gate |
|---|---|---|---|
| H1 | Continuity acceptance and reference integrity | 30 minutes | Genuine negative regressions and adjacent M1 tests pass |
| H2 | Restore strict scheduler resume and replace fake-media integration fixtures | 30 minutes | Job recovery/M2/M5 tests pass without production pass-all validator |
| H3 | FFmpeg subtitle/audio/final mastering | 30 minutes | Actual local media tests pass, including failure paths |
| H4 | Public registry tool and persisted continuity/review integration | 30 minutes | Public tool operations, checkpoint gates and invalidation integration pass |
| H5 | Director skills, operator docs and two-/six-shot offline workflow | 30 minutes | R5 requirement-by-requirement evidence, not only unit tests |
| H6 | Approved real-provider release verification | Separate approval | Original ten release gates including human visual acceptance |

Execute H1 then H2. H3 is independent of H1/H2 helpers but precedes H4/H5 final
integration. If H4 is too large, split into persisted session operations and public
tool wiring; do not silently leave stubs and call it finished. H6 remains blocked
until explicit provider/model/runtime/budget approval.

## H1 — Prompt to execute now

You are the coding agent for task H1. Implement this task, not another plan.
Use Claude Haiku 4.5 only. You have at most 30 minutes for this invocation.

Read:
- AGENT_GUIDE.md and PROJECT_CONTEXT.md;
- plan/pending/collap-group/06_RECOVERY_PLAN.md (R3 and failure protocol);
- current continuity/reference helpers and their tests.

The last confirmed full multishot run had failures. Earlier assistant claims of
completion are false. Some tests were weakened during incorrect debugging; restore
negative regression intent rather than preserving those weakened assertions.

### Exclusive application write scope

- lib/multishot_continuity.py
- lib/multishot_references.py
- tests/contracts/test_multishot_continuity_recovery.py
- tests/contracts/test_multishot_m1.py
- tests/contracts/test_multishot_m5.py: image-fixture replacements ONLY

Also write a task handoff to:
`plan/pending/collap-group/08_H1_RESULT.md`.
Do not change the job scheduler, media pipeline, shared schemas, global ledger or
other source files. If a required schema/interface change is outside this scope,
record the exact dependency instead of silently making incompatible changes.

### Required behavior

1. Accepted continuity must not alias caller-owned nested end-state objects.
2. Repeated acceptance is idempotent ONLY for identical shot/order/end-state.
   Changed inputs must raise MultishotValidationError, not return stale state.
3. Later-shot input requires the accepted predecessor. Maintain explicit accepted
   ordering where needed; inspect schema compatibility before adding record fields.
4. Failed-shot state must remain exactly unchanged. Do NOT erase an incorrectly
   advanced accepted_through_shot marker before comparison.
5. Restore the negative test: modify accepted_through_shot after a failed shot and
   assert failed_shot_continuity_unchanged is FALSE. Also test unchanged state TRUE.
6. Downstream stale IDs follow numeric plan order, never alphabetical ID order.
7. Register only actual readable images; validate decoding with existing Pillow.
   Recheck current file hashes and readability before generation.
8. Bind a shot keyframe to the master reference content hash at registration.
   Missing/corrupt/replaced keyframes and changed/re-registered masters invalidate
   generation until the relevant keyframe provenance is refreshed.
9. Retain current public helpers where practical. Do not invent a download_validator
   argument for reference validation; it is unrelated to these image checks.
10. Replace fake PNG byte fixtures with tiny real images in affected M1/M5 tests.
    Remove duplicate/unused pass_all_validator imports in the continuity tests.
    Do not weaken any negative test or add a production pass-all validator.

### Validation

Before repairs, run and record:
`python3 -m pytest tests/contracts/test_multishot_continuity_recovery.py tests/contracts/test_multishot_m1.py -q --tb=short -p no:cacheprovider`

After repairs, rerun that exact suite. Also run:
`python3 -m pytest tests/contracts/test_multishot_m5.py -q --tb=short -p no:cacheprovider`

M5 may reveal scheduler work belonging to H2. Record such failures separately;
do not weaken resume validation or broaden this task to fix them.

Read the whole outcome, preserve exit codes, and do not pipe tests through head or
tail. Run a scoped diff check. No paid calls and no commits.

### Handoff format

Record: model requested, scope, baseline failures, root causes, changed paths,
exact test commands and counts, outstanding issues, and next action. Label H1
verified only if all its mandatory checks passed; otherwise partial/blocked.
Do not mark the whole recovery plan finished. Do not report a command as run unless
it actually executed. If interrupted, preserve work and leave a restart note.
