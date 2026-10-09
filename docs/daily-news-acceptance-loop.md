# Daily-news strict acceptance loop

The controller runs a fixed regression suite and verifies three independent
reports produced by the actual `scripts/run_daily_news_pipeline.sh
--rehearsal-bundle ...` entrypoint. It accepts evidence only; it does not execute
the production shell, render, publish, spend, deploy, observe cron, or mark a
plan complete. Stage-root isolation is an external prerequisite: the shell
report explicitly says egress isolation is not asserted. Run reports only from
disposable, isolated roots under the runtime environment's approved controls.

## Invocation

Run from the approved isolated runtime checkout, not a developer workstation or
the stable production checkout:

```sh
python3 scripts/run_daily_news_acceptance_loop.py \
  --state-dir /var/tmp/daily-news-acceptance \
  --rehearsal-manifest /evidence/run-1.json \
  --rehearsal-manifest /evidence/run-2.json \
  --rehearsal-manifest /evidence/run-3.json \
  --wall-seconds 1800 --suite-timeout 1500
```

The suite is hard-coded: actual daily rehearsal execution/preflight, offline
rehearsal contracts, transport injection, failure preservation, evidence/release
gates, caption installation/timing/integration, strict publish preflight and
manual publish regression, schedule regression, cron retry, and this controller's
contract tests. It uses `sys.executable`, emits JUnit,
and requires at least one collected test with zero failures, errors, and skips.
The suite command and test selectors are not user-configurable. The subprocess
is process-group bounded and receives the smaller of suite timeout and remaining
durable wall-clock budget. `PYTEST_ADDOPTS` and `PYTEST_PLUGINS` are removed from
the child environment and pytest `addopts` is explicitly overridden; this does
not disable all possible pytest configuration or installed entry-point plugins.
No completed report is accepted for resume unless its fixed argv, exit code,
contained log/JUnit paths, source/input fingerprint, log/JUnit hashes, and
re-parsed JUnit summary still validate.

State is atomically persisted before starting each attempt. A timeout is retried
once in the same invocation only when the attempt cap and remaining durable wall
budget permit it (default `--max-attempts 2`, or `1` to disable retries). Exhausted
timeouts stop with `suite_timeout`. User SIGINT/SIGTERM is recorded and returned
immediately without same-invocation retry; an explicit later resume may consume
the remaining global attempt budget. Deterministic failures are never retried
under the same fingerprint. A changed source/input fingerprint can permit a fresh attempt
while retaining superseded fingerprints and attempt history. The attempt cap and
wall-clock budget apply across fingerprint changes, not per fingerprint. Attempt
outputs use unique fingerprint/time directories and are never reused. Malformed
state fails closed without overwriting it. State directory components and
lock/state/report/output paths reject symlinks; the lock uses `O_NOFOLLOW` where
available. SIGTERM/SIGINT during the suite kills its process group, durably
records interruption, and restores the prior signal handler. An exclusive lock
returns exit 73 on overlap. A passing
test suite and valid reports still exit 2 with
`blocked_external_approval`: `plan_complete` remains false, and human sample
approval, deployment authorization, and live cron observation remain
`unverified`.

Manifest, marker, report, and evidence reads are size-bounded; JSON is parsed
from the exact bytes whose SHA-256 values are recorded. The controller compares
those snapshots with its source/input fingerprint and verifies them again before
accepting or reusing suite success. Any intervening change blocks as
`blocked_evidence_changed`; a rejected symlink manifest is excluded from input
fingerprinting but still blocks rehearsal evidence, while the fixed suite runs.
`next-action.json` gives a status-specific remediation with report details.

Reports/logs are written under the supplied state directory: `state.json`,
`attempt.json`, unique `attempt-<fingerprint>-<time>-<number>/` directories with
`acceptance.log` and `junit.xml`, `report.json`, and `controller.lock`. Preserve
this directory for audit and resume. Missing or
invalid rehearsal inputs do not bypass the fixed suite, but final status is
blocked and nonzero.

## Manifest and full-run evidence contract

Pass exactly three distinct JSON manifests. Each references one complete
successful full-shell rehearsal, not a component stage or a replay. Example:

```json
{
  "isolated_root": "/evidence/run-1-root",
  "report": "/evidence/run-1-root/logs/daily_news_rehearsal_report.json",
  "failure_evidence": "logs/negative-path-observation.log",
  "recovery_evidence": "logs/recovery-observation.log"
}
```

The root must carry `.openmontage-rehearsal-root.json` with exact contents
`{"test_only":true,"purpose":"daily-news-rehearsal"}` and must not be a git
checkout. The report path must be the canonical `logs/daily_news_rehearsal_report.json`
inside that root. The report must match the actual writer's contract:

- `test_only: true`, `shell_executed: true`, `publication_enabled: false`,
  `n5_complete: false`;
- `requested_project_ids` contains exactly three unique IDs and
  `successful_project_ids` equals that exact ordered list;
- `failed_project_ids` and `quarantined_project_ids` are empty;
- `terminal_exit_status: 0` and `terminal_stage: "completed"`;
- `stage_evidence_paths` contains nonempty existing files for each requested ID.

The three reports must have distinct isolated roots and pairwise-distinct
requested-ID sets. Each requested ID must match the safe ASCII project-ID
format. Each evidence path is checked as an existing regular file contained in its
run root, then SHA-256 hashed. The manifest's distinct `failure_evidence` and
`recovery_evidence` paths are likewise required to exist under that root and are
hashed; they are separate negative-path/recovery observations, not string
claims. Report hashes, paths, and per-project evidence hashes are preserved in
the controller output. The controller verifies fields and bytes, but cannot
cryptographically prove that an external report's claims are truthful.

The shell report does not claim network isolation, publication success, human
approval, N5/release completion, or deployment readiness. This controller does
not interpret it as doing so and never returns a plan-complete status. No
arbitrary shell command can be supplied to the runner.

## Verified checkpoint

The implementation was tested in `/home/ubuntu/OpenMontage-daily-news-render-repair`,
not the stable deployment. The broad regression run passed 1,329 tests with
7 skips and 19 subtests; those broader-suite skips are **not** permitted by the
controller's separate strict suite.

The real controller run at
`/home/ubuntu/OpenMontage-daily-news-acceptance/loop-20261010-02` ran 240 tests
with zero failures, errors, or skips. It exited 2 with
`blocked_missing_rehearsal_inputs` and `plan_complete: false`. A second invocation
reused the hash-verified result; the attempt count remained 1. No positive
three-run rehearsal evidence was supplied or claimed. The broad-suite JUnit
record is `projects/render-freeze-rehearsal/qa/acceptance-loop-regression-results.xml`.

This is a verification loop, not an autonomous coding or deployment agent. The
coding supervisor reads `next-action.json`, repairs source locally using the
approved coding agent, synchronizes the repaired revision into the isolated
server checkout, and resumes verification within its remaining budget. An
exhausted budget requires a new explicitly supervised cycle; retain the old
state directory. Missing source/media bundles or human release decisions must
be resolved by supplying those inputs, not by disabling checks.
