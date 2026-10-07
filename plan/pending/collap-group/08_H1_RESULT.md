# H1 Result — Continuity and Reference Acceptance Repair

## Status

`blocked` / `implemented_unverified`

H1-only source and contract repairs are present locally, but required remote validation could not be completed because synchronizing files to `sandbox-video` requires an approval-gated `scp` operation that was denied. This report does not claim the recovery plan or H2 complete.

## Supervisor follow-up

The 30-minute bounded invocation returned normally after approximately 13 minutes.
CLI initialization and final model-usage metadata both reported
`claude-haiku-4-5-20251001`; no model fallback was used. Session:
`98209231-ed08-498c-bcdf-62c67b0be1b3`.

The supervisor subsequently ran the three focused files locally:

```sh
python3 -m pytest tests/contracts/test_multishot_continuity_recovery.py tests/contracts/test_multishot_m1.py tests/contracts/test_multishot_m5.py -q --tb=short -p no:cacheprovider
```

Result: **44 passed in 0.44s**, exit 0. This is local evidence only, not the
required remote-environment validation. CLAUDE.md's remote-execution instruction
was discovered afterward; subsequent project commands must use that environment.
No remote synchronization is claimed.

Source review still finds acceptance gaps not covered by those passing tests:
- Later-shot input checks that *some* predecessor is accepted, not that it is
  the immediate predecessor of the requested shot.
- Repeat acceptance compares the merged result rather than the original accepted
  payload; a different payload producing the same state can still pass.
- Keyframe master provenance can be absent and therefore skipped; the next review
  must enforce required identity-reference coverage rather than only validate
  provenance when supplied.
- Scoped diff check reports trailing whitespace in lib/multishot_continuity.py.

H1 remains **partial**, not fully verified. Assign a bounded Haiku-only H1
follow-up for these gaps and their negative tests before advancing to H2.
The scheduler remains an H2 concern; passing M5 fixtures here do not validate
its previously weakened resume provenance checks.

## Requested model

Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), as requested.

## Scope

H1 only: immutable continuity acceptance and exact repeat semantics; predecessor and accepted-order checks; failed-shot continuity immutability; numeric downstream stale ordering; readable image registration using Pillow; current keyframe/master hash validation; keyframe-to-master provenance binding; and real image fixtures in affected M1/M5 tests.

No scheduler, provider, checkpoint, workspace, schema, pipeline, H2, H3, H4, H5, H6, or M6 work was started by this H1 repair.

## Baseline

The required baseline command was attempted remotely with the system interpreter and failed because pytest is unavailable in `/usr/bin/python3`:

```text
/usr/bin/python3: No module named pytest
```

A second attempt reached pytest through the project interpreter but failed before collection because the remote checkout did not contain the untracked H1 recovery test:

```text
ERROR: file or directory not found: tests/contracts/test_multishot_continuity_recovery.py
no tests ran in 0.00s
```

No valid baseline count is available.

## Root causes addressed

- Repeated acceptance now compares supplied end state and order.
- Later-shot continuity now requires an accepted predecessor.
- Failed-shot comparison now detects any state mutation, including an advanced marker.
- Reference hashing now requires a readable Pillow image.
- Generation readiness rechecks current file content and keyframe/master provenance.
- The content-hash fixture now uses a real tiny PNG.

## Changed paths

- `lib/multishot_continuity.py`
- `lib/multishot_references.py`
- `tests/contracts/test_multishot_continuity_recovery.py`
- `tests/contracts/test_multishot_m1.py`
- `tests/contracts/test_multishot_m5.py`
- `plan/pending/collap-group/08_H1_RESULT.md`

Unrelated dirty files were preserved. No commit or branch change was made.

## Validation commands

```text
python3 -m pytest tests/contracts/test_multishot_continuity_recovery.py tests/contracts/test_multishot_m1.py -q --tb=short -p no:cacheprovider
python3 -m pytest tests/contracts/test_multishot_m5.py -q --tb=short -p no:cacheprovider
```

Post-repair counts and exit codes: **not available**. Remote synchronization was denied before execution.

## Code review

Scoped review found one HIGH contract issue: `test_content_hash_is_sha256` wrote `b"hello"` while `content_hash()` required a readable image. The fixture was corrected to save a tiny Pillow PNG. No CRITICAL issues were found.

## Outstanding issues

- Synchronize H1 files to `sandbox-video` through an approved mechanism.
- Run both exact post-repair commands remotely.
- Record exact pass/fail counts and exit codes.
- Record any M5 scheduler failures separately as H2; do not broaden H1.

## Next action

In an approval-enabled session, copy the H1 paths to `sandbox-video`, run both exact commands, update this report with sanitized outputs/counts, and mark H1 `verified` only if checks pass.

## Restart note

Session stopped at approval-gated remote synchronization. Local edits remain. Last blocker: `scp` was denied before execution. No remote post-repair test has run. Resume by syncing listed H1 paths, then run the exact focused tests; do not start H2 or commit.
